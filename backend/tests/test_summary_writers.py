"""Every summary writer records the same summary, on Postgres with a scripted LLM.

Before the artifact summary module each writer stored a summary its own
way. The local loader kept only the four text lines, dropping the clarity
lists and the prompt version. The admin and news writers fell back to the
title. The repair operation had its own rule for an incomplete summary.
Here each writer summarises one artifact from the same scripted answer, and
every one must read back the same summary from one row. The worker's
document path is covered in test_pipeline_stages.py. The admin summary
routes now queue a summary request, the writer here.
"""

import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.messages import StoredTextAnalysisMessage, SummaryRequestMessage
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.models.ticker import Ticker
from app.services import artifact_summary
from app.services.generation import providers
from app.services.generation.providers import ScriptedProvider
from app.status import AnalysisStatus
from lambdas import analysis, pipeline_stage
from lambdas.artifact_analysis import AnalysisPorts, FinBertScorer
from lambdas.artifact_analysis_records import PostgresAnalysisRecords
from parsing import storage
from parsing.classification import ClassificationInput, classify_document
from scrapers.base import Announcement

MODEL = "bedrock:test-model"
ANNOUNCEMENT_ANSWER = {
    "summary": "CSL reported higher half year revenue.",
    "about": "The report covers CSL's half year results.",
    "changed": "Revenue increased.",
    "matters": "Higher revenue may support earnings.",
    "confirmed_facts": ["Revenue increased."],
    "speculation": ["Earnings may rise next year."],
}
NEWS_ANSWER = {
    "summary": "BHP reported higher copper production.",
    "about": "The story covers BHP's quarterly copper output.",
    "changed": "Reported production increased.",
    "matters": "The increase may affect revenue expectations.",
}
ANNOUNCEMENT_TEXT = "Half year report for the six months ended 31 December 2025."
# A well-formed announcement answer the model left empty.
EMPTY_ANSWER = {
    **{key: "" for key in artifact_summary.TEXT_LINES},
    "confirmed_facts": [],
    "speculation": [],
}

Writer = Callable[[Session, pytest.MonkeyPatch], Artifact]


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"Database is not available: {exc}")
    connection = engine.connect()
    transaction = connection.begin()
    # The writers run on SessionLocal, which does not autoflush. Nor does this.
    session = sessionmaker(bind=connection, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def finbert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.sentiment.analyse_text",
        MagicMock(
            return_value={
                "sentiment_label": "positive",
                "label": "positive",
                "confidence_score": 0.9,
                "model_used": "test-finbert",
            }
        ),
    )


@pytest.fixture()
def bedrock(monkeypatch: pytest.MonkeyPatch):
    """Script the answers, as Bedrock, which the repair operation requires."""

    def install(*answers: dict) -> ScriptedProvider:
        provider = ScriptedProvider([json.dumps(answer) for answer in answers], name=MODEL)
        monkeypatch.setattr(providers, "configured_provider", lambda: provider)
        return provider

    return install


def _workers_use(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def test_session():
        yield db

    monkeypatch.setattr(pipeline_stage, "database_session", test_session)
    monkeypatch.setattr(
        analysis,
        "deployed_ports",
        lambda: AnalysisPorts(
            records=PostgresAnalysisRecords(test_session),
            scorer=FinBertScorer(),
        ),
    )


def _artifact(db: Session, **values) -> Artifact:
    bhp = db.scalars(select(Ticker).where(Ticker.symbol == "BHP")).one()
    artifact = Artifact(
        ticker_id=bhp.id,
        content_hash=f"writers-{uuid.uuid4()}",
        published_at=datetime.now(timezone.utc) - timedelta(days=1),
        **values,
    )
    db.add(artifact)
    db.commit()
    return artifact


def _announcement(db: Session, **values) -> Artifact:
    return _artifact(
        db,
        source_type="asx_announcement",
        artifact_type="half_year_results",
        title="Half Year Results",
        raw_text=ANNOUNCEMENT_TEXT,
        **values,
    )


def _news(db: Session) -> Artifact:
    return _artifact(
        db,
        source_type="news",
        artifact_type="news_article",
        title="BHP lifts copper output",
        raw_text="BHP reported an increase in quarterly copper production.",
        artifact_metadata={"source_name": "Example News"},
    )


def _local_loader(db: Session, monkeypatch: pytest.MonkeyPatch) -> Artifact:
    monkeypatch.setattr(storage, "SessionLocal", lambda: db)
    monkeypatch.setattr(storage.time, "sleep", lambda _seconds: None)
    raw_text = f"{ANNOUNCEMENT_TEXT} {uuid.uuid4()}"
    announcement = Announcement(
        ticker="CSL",
        title="Half Year Results",
        date=datetime(2026, 2, 1, tzinfo=timezone.utc),
        pdf_url=f"https://investors.csl.com/pdf/{uuid.uuid4()}.pdf",
        source_url="https://investors.csl.com/investors/asx-announcements",
    )
    storage.store(
        announcement,
        classification=classify_document(
            ClassificationInput(
                title=announcement.title,
                text=raw_text,
                filename="report.pdf",
                source_type="asx_announcement",
                source_adapter="csl",
            )
        ),
        extracted_data={},
        raw_text=raw_text,
    )
    return db.scalars(
        select(Artifact).where(Artifact.content_hash == storage.compute_content_hash(raw_text))
    ).one()


def _analysed_announcement(db: Session, created_day: int, answer: dict) -> Artifact:
    """An analysed announcement whose summary an earlier model recorded."""
    artifact = _announcement(
        db,
        analysis_status=AnalysisStatus.COMPLETED,
        created_at=datetime(2000, 1, created_day, tzinfo=timezone.utc),
    )
    artifact_summary.record(
        db,
        artifact,
        artifact_summary.from_answer(
            answer,
            model="bedrock:earlier-model",
            prompt_version="llm-announcement-summary-v2",
        ),
    )
    db.commit()
    return artifact


def _repair(limit: int) -> dict:
    return analysis.handler(
        {
            "operation": "resummarise_missing_fields",
            "apply": True,
            "confirmation": "RESUMMARISE_MISSING_FIELDS",
            "limit": limit,
        },
        None,
    )


def _lines_only(answer: dict) -> dict:
    return {key: answer[key] for key in artifact_summary.TEXT_LINES}


def _repair_operation(db: Session, monkeypatch: pytest.MonkeyPatch) -> Artifact:
    artifact = _analysed_announcement(db, 1, _lines_only(ANNOUNCEMENT_ANSWER))
    _workers_use(db, monkeypatch)
    _repair(limit=1)
    return artifact


def _handle(message: StoredTextAnalysisMessage | SummaryRequestMessage) -> None:
    analysis.handler(
        {
            "Records": [
                {
                    "messageId": "message-1",
                    "body": message.model_dump_json(),
                    "attributes": {"ApproximateReceiveCount": "1"},
                }
            ]
        },
        None,
    )


def _analysis_worker(db: Session, monkeypatch: pytest.MonkeyPatch) -> Artifact:
    artifact = _news(db)
    _workers_use(db, monkeypatch)
    _handle(StoredTextAnalysisMessage(artifact_id=artifact.id))
    return artifact


def _summary_request(new_artifact: Callable[[Session], Artifact]) -> Writer:
    def write(db: Session, monkeypatch: pytest.MonkeyPatch) -> Artifact:
        artifact = new_artifact(db)
        _workers_use(db, monkeypatch)
        _handle(SummaryRequestMessage(artifact_id=artifact.id))
        return artifact

    return write


def _summary_rows(db: Session, artifact: Artifact) -> list[ArtifactSummary]:
    return list(
        db.scalars(select(ArtifactSummary).where(ArtifactSummary.artifact_id == artifact.id))
    )


@pytest.mark.parametrize(
    "writer",
    [_local_loader, _repair_operation, _summary_request(_announcement)],
    ids=["local_loader", "repair_operation", "summary_request"],
)
def test_every_announcement_writer_records_the_same_summary(
    db_session: Session,
    bedrock,
    monkeypatch: pytest.MonkeyPatch,
    writer: Writer,
) -> None:
    bedrock(ANNOUNCEMENT_ANSWER)

    artifact = writer(db_session, monkeypatch)

    assert artifact_summary.read(artifact) == artifact_summary.from_answer(
        ANNOUNCEMENT_ANSWER,
        model=MODEL,
        prompt_version="llm-announcement-summary-v3",
    )
    assert len(_summary_rows(db_session, artifact)) == 1


@pytest.mark.parametrize(
    "writer",
    [_analysis_worker, _summary_request(_news)],
    ids=["analysis_worker", "summary_request"],
)
def test_every_news_writer_records_the_same_summary(
    db_session: Session,
    bedrock,
    monkeypatch: pytest.MonkeyPatch,
    writer: Writer,
) -> None:
    bedrock(NEWS_ANSWER)

    artifact = writer(db_session, monkeypatch)

    assert artifact_summary.read(artifact) == artifact_summary.from_answer(
        NEWS_ANSWER,
        model=MODEL,
        prompt_version="llm-news-summary-v2",
    )
    assert len(_summary_rows(db_session, artifact)) == 1


def test_the_local_loader_stores_sentiment_for_an_answer_without_text(
    db_session: Session,
    bedrock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = bedrock(EMPTY_ANSWER)

    artifact = _local_loader(db_session, monkeypatch)

    assert len(provider.calls) == 1
    assert artifact_summary.read(artifact) is None
    assert _summary_rows(db_session, artifact) == []
    sentiments = db_session.scalars(
        select(ArtifactSentiment).where(ArtifactSentiment.artifact_id == artifact.id)
    ).all()
    assert [sentiment.model_used for sentiment in sentiments] == ["test-finbert"]
