"""The local content loader, on Postgres with a fake source adapter.

It used to run its own pipeline: pypdf only, its own summary and sentiment
writes, and no analysis status. Now each document goes through the artifact
analysis module, as the analysis worker's documents do.
"""

import asyncio
import json
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.models.artifact import Artifact
from app.services import artifact_summary
from app.services.generation.providers import ScriptedProvider
from app.services.llm_errors import LLMUnavailableError
from app.status import AnalysisStatus
from lambdas.artifact_analysis import AnalysisPorts, FixedSentiment
from lambdas.artifact_analysis_records import PostgresAnalysisRecords
from lambdas.download_validation import validated_document
from scripts import populate_local_content
from scripts.populate_local_content import bounded_announcements
from scrapers.base import Announcement

REPORT = b"Half year report for the six months ended 31 December 2025."
SUMMARY = {
    "summary": "CSL reported higher half year revenue.",
    "about": "The report covers CSL's half year results.",
    "changed": "Revenue increased.",
    "matters": "Higher revenue may support earnings.",
    "confirmed_facts": ["Revenue increased."],
    "speculation": [],
}


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
    session = sessionmaker(bind=connection, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def _announcement(title: str, age_days: int) -> Announcement:
    return Announcement(
        ticker="CSL",
        title=title,
        date=datetime.now(timezone.utc) - timedelta(days=age_days),
        pdf_url=f"https://example.test/{title}.pdf",
        source_url="https://example.test/asx",
    )


class Adapter:
    """Lists one announcement and fetches it as a text document."""

    def __init__(self, announcement: Announcement) -> None:
        self.announcement = announcement
        self.fetched: list = []

    async def list_documents(self):
        return [self.announcement]

    async def fetch_document(self, request, *, max_bytes):
        self.fetched.append(request)
        return validated_document(
            REPORT,
            declared_content_type="text/plain",
            final_url=request.document_url,
            max_bytes=max_bytes,
        )


def _ports(db: Session, *answers: dict | Exception) -> AnalysisPorts:
    return AnalysisPorts(
        records=PostgresAnalysisRecords(lambda: nullcontext(db)),
        scorer=FixedSentiment("positive"),
        provider=ScriptedProvider(
            [json.dumps(answer) if isinstance(answer, dict) else answer for answer in answers]
        ),
    )


def _collect(db: Session, tmp_path, ports: AnalysisPorts) -> dict:
    return asyncio.run(
        populate_local_content.collect_asx(
            ["CSL"],
            lookback_days=30,
            max_documents=3,
            output_dir=tmp_path,
            session_scope=lambda: nullcontext(db),
            ports=ports,
        )
    )


def test_bounded_announcements_keeps_only_recent_documents_within_limit() -> None:
    selected = bounded_announcements(
        [_announcement("older", 20), _announcement("newest", 1), _announcement("old", 90)],
        lookback_days=30,
        max_documents=1,
    )

    assert [announcement.title for announcement in selected] == ["newest"]


def test_collect_asx_saves_each_document_and_analyses_it_once(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    announcement = _announcement("Half Year Results", 1)
    adapter = Adapter(announcement)
    monkeypatch.setattr(populate_local_content, "adapter_for", lambda _ticker: adapter)
    ports = _ports(db_session, SUMMARY)

    first = _collect(db_session, tmp_path, ports)
    again = _collect(db_session, tmp_path, ports)

    [artifact] = db_session.scalars(
        select(Artifact).where(Artifact.content_hash.like("document:%"))
    ).all()
    assert first == again == {"found": 1, "processed": 1, "errors": []}
    assert [request.document_url for request in adapter.fetched] == [announcement.pdf_url] * 2
    assert announcement.local_path.parent == tmp_path / "CSL"
    assert announcement.local_path.read_bytes() == REPORT
    assert len(ports.scorer.scored) == 1
    assert (artifact.analysis_status, artifact.scrape_run_id) == (AnalysisStatus.COMPLETED, None)
    assert artifact.raw_text == REPORT.decode()
    assert artifact.artifact_metadata["classification"]["primary_category"] == (
        "half_year_results"
    )
    assert artifact_summary.read(artifact).prompt_version == "llm-announcement-summary-v3"


def test_a_later_run_summarises_a_document_first_analysed_without_an_llm(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    adapter = Adapter(_announcement("Half Year Results", 1))
    monkeypatch.setattr(populate_local_content, "adapter_for", lambda _ticker: adapter)

    _collect(db_session, tmp_path, _ports(db_session, LLMUnavailableError("No LLM key")))
    ports = _ports(db_session, SUMMARY)
    _collect(db_session, tmp_path, ports)

    [artifact] = db_session.scalars(
        select(Artifact).where(Artifact.content_hash.like("document:%"))
    ).all()
    assert ports.scorer.scored == []
    assert artifact_summary.is_complete(
        artifact_summary.read(artifact),
        source_type="asx_announcement",
    )
