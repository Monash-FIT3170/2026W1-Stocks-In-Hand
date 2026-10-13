"""Summary writers record the whole summary, on Postgres with a scripted LLM.

The local loader used to keep only the four text lines, dropping the
clarity lists and the prompt version, and overwrote an earlier prompt
version with NULL. The summary repair operation had its own rule for which
summaries were incomplete.
"""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.models.artifact import Artifact
from app.services import artifact_summary
from app.services.generation import providers
from app.services.generation.providers import ScriptedProvider
from app.status import AnalysisStatus
from lambdas import analysis
from parsing import storage
from parsing.classification import ClassificationInput, classify_document
from scrapers.base import Announcement

ANNOUNCEMENT_ANSWER = {
    "summary": "CSL reported higher half year revenue.",
    "about": "The report covers CSL's half year results.",
    "changed": "Revenue increased.",
    "matters": "Higher revenue may support earnings.",
    "confirmed_facts": ["Revenue increased."],
    "speculation": ["Earnings may rise next year."],
}
ANNOUNCEMENT_SUMMARY = artifact_summary.from_answer(
    ANNOUNCEMENT_ANSWER,
    model="scripted:test-model",
    prompt_version="llm-announcement-summary-v3",
)


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
    session = sessionmaker(bind=connection)()
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
def scripted(monkeypatch: pytest.MonkeyPatch):
    def install(*answers: dict) -> ScriptedProvider:
        provider = ScriptedProvider([json.dumps(answer) for answer in answers])
        monkeypatch.setattr(providers, "configured_provider", lambda: provider)
        return provider

    return install


def test_the_local_loader_records_the_whole_summary(
    db_session: Session,
    scripted,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(storage.time, "sleep", lambda _seconds: None)
    scripted(ANNOUNCEMENT_ANSWER)
    raw_text = f"Half year report for the six months ended 31 December 2025. {uuid.uuid4()}"
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

    artifact = db_session.scalars(
        select(Artifact).where(Artifact.content_hash == storage.compute_content_hash(raw_text))
    ).one()
    assert artifact_summary.read(artifact) == ANNOUNCEMENT_SUMMARY
    assert len(artifact.summaries) == 1


def test_the_repair_operation_completes_incomplete_announcement_summaries(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def test_session():
        yield db_session

    monkeypatch.setattr(analysis, "database_session", test_session)

    def analysed(created_day: int, answer: dict, model: str) -> Artifact:
        artifact = Artifact(
            source_type="asx_announcement",
            artifact_type="half_year_results",
            title="Half Year Results",
            raw_text="Half year report for the six months ended 31 December 2025.",
            content_hash=f"repair-{uuid.uuid4()}",
            analysis_status=AnalysisStatus.COMPLETED,
            created_at=datetime(2000, 1, created_day, tzinfo=timezone.utc),
        )
        db_session.add(artifact)
        db_session.flush()
        artifact_summary.record(
            db_session,
            artifact,
            artifact_summary.from_answer(
                answer,
                model=model,
                prompt_version="llm-announcement-summary-v2",
            ),
        )
        return artifact

    lines_only = {key: ANNOUNCEMENT_ANSWER[key] for key in artifact_summary.TEXT_LINES}
    incomplete = analysed(1, lines_only, "bedrock:earlier-model")
    unrepaired = analysed(2, lines_only, "bedrock:earlier-model")
    complete = analysed(1, ANNOUNCEMENT_ANSWER, "bedrock:earlier-model")
    db_session.commit()
    provider = ScriptedProvider(
        [json.dumps(ANNOUNCEMENT_ANSWER), json.dumps({**ANNOUNCEMENT_ANSWER, "matters": ""})],
        name="bedrock:test-model",
    )
    monkeypatch.setattr(providers, "configured_provider", lambda: provider)

    result = analysis.handler(
        {
            "operation": "resummarise_missing_fields",
            "apply": True,
            "confirmation": "RESUMMARISE_MISSING_FIELDS",
            "limit": 5,
        },
        None,
    )

    assert artifact_summary.read(incomplete) == artifact_summary.from_answer(
        ANNOUNCEMENT_ANSWER,
        model="bedrock:test-model",
        prompt_version="llm-announcement-summary-v3",
    )
    assert artifact_summary.read(complete).model == "bedrock:earlier-model"
    assert artifact_summary.read(unrepaired).model == "bedrock:earlier-model"
    assert {
        "artifact_id": str(unrepaired.id),
        "error": "RuntimeError: Bedrock response omitted structured summary fields",
    } in result["failed"]
    assert result["missing_after"] == result["missing_before"] - 1
