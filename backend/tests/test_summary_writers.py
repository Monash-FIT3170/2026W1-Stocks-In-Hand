"""Every summary writer records the same summary, on Postgres with a scripted LLM.

Before the artifact summary module each writer stored a summary its own
way. The local loader kept only the four text lines, dropping the clarity
lists and the prompt version. The admin and news writers fell back to the
title. The repair operation had its own rule for an incomplete summary.
Here each writer summarises one artifact from the same scripted answer, and
every one must read back the same summary from one row. The worker's
document path is covered in test_pipeline_stages.py.
"""

import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.routes import llm
from app.core.config import settings
from app.messages import PublicDiscussionAnalysisMessage
from app.models.artifact import Artifact
from app.models.artifact_summary import ArtifactSummary
from app.models.ticker import Ticker
from app.services import artifact_summary, news_summary
from app.services.generation import providers
from app.services.generation.providers import ScriptedProvider
from app.status import AnalysisStatus
from lambdas import analysis, pipeline_stage
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

    for module in (analysis, pipeline_stage):
        monkeypatch.setattr(module, "database_session", test_session)


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


def _admin_route(new_artifact: Callable[[Session], Artifact]) -> Writer:
    def write(db: Session, _monkeypatch: pytest.MonkeyPatch) -> Artifact:
        artifact = new_artifact(db)
        llm.summarise_artifact(artifact_id=artifact.id, db=db)
        return artifact

    return write


def _admin_ticker_route(db: Session, _monkeypatch: pytest.MonkeyPatch) -> Artifact:
    artifact = _announcement(db)
    llm.summarise_ticker_artifacts("BHP", db=db)
    return artifact


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


def _analysis_worker(db: Session, monkeypatch: pytest.MonkeyPatch) -> Artifact:
    artifact = _news(db)
    _workers_use(db, monkeypatch)
    message = PublicDiscussionAnalysisMessage(artifact_id=artifact.id)
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
    return artifact


def _news_service(db: Session, _monkeypatch: pytest.MonkeyPatch) -> Artifact:
    artifact = _news(db)
    news_summary.summarise_news_artifact(db, artifact)
    return artifact


def _summary_rows(db: Session, artifact: Artifact) -> list[ArtifactSummary]:
    return list(
        db.scalars(select(ArtifactSummary).where(ArtifactSummary.artifact_id == artifact.id))
    )


@pytest.mark.parametrize(
    "writer",
    [_admin_route(_announcement), _admin_ticker_route, _local_loader, _repair_operation],
    ids=["admin_artifact_route", "admin_ticker_route", "local_loader", "repair_operation"],
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
    [_analysis_worker, _news_service, _admin_route(_news)],
    ids=["analysis_worker", "news_service", "admin_artifact_route"],
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


def test_the_repair_operation_completes_only_incomplete_announcement_summaries(
    db_session: Session,
    bedrock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = _analysed_announcement(db_session, 1, _lines_only(ANNOUNCEMENT_ANSWER))
    unrepaired = _analysed_announcement(db_session, 2, _lines_only(ANNOUNCEMENT_ANSWER))
    complete = _analysed_announcement(db_session, 1, ANNOUNCEMENT_ANSWER)
    _workers_use(db_session, monkeypatch)
    bedrock(ANNOUNCEMENT_ANSWER, {**ANNOUNCEMENT_ANSWER, "matters": ""})

    result = _repair(limit=5)

    assert artifact_summary.read(incomplete) == artifact_summary.from_answer(
        ANNOUNCEMENT_ANSWER,
        model=MODEL,
        prompt_version="llm-announcement-summary-v3",
    )
    assert artifact_summary.read(complete).model == "bedrock:earlier-model"
    assert artifact_summary.read(unrepaired).model == "bedrock:earlier-model"
    assert {
        "artifact_id": str(unrepaired.id),
        "error": "RuntimeError: Bedrock response omitted structured summary fields",
    } in result["failed"]
    assert result["missing_after"] == result["missing_before"] - 1


def test_the_repair_operation_lists_an_announcement_removed_while_it_was_summarised(
    db_session: Session,
    bedrock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed = _analysed_announcement(db_session, 1, _lines_only(ANNOUNCEMENT_ANSWER))
    removed_id = removed.id
    _workers_use(db_session, monkeypatch)
    provider = bedrock(ANNOUNCEMENT_ANSWER)
    answer = provider.complete

    def remove_then_answer(prompt: str, **options) -> str:
        db_session.execute(
            delete(ArtifactSummary).where(ArtifactSummary.artifact_id == removed_id)
        )
        db_session.execute(delete(Artifact).where(Artifact.id == removed_id))
        return answer(prompt, **options)

    monkeypatch.setattr(provider, "complete", remove_then_answer)

    result = _repair(limit=1)

    assert result["updated"] == 0
    assert result["failed"] == [
        {
            "artifact_id": str(removed_id),
            "error": "RuntimeError: Completed artifact is no longer available",
        }
    ]
