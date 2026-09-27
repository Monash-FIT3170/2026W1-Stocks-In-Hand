"""Retryable pipeline failures stay non-terminal until SQS gives up.

Each worker used to record a terminal FAILED state on every retryable error.
The retry then undid it, but in between the run could be reported finished,
and the API or scheduler could enqueue a second Queue A message for a run
that SQS was still redelivering. Only the receive that matches the queues'
maxReceiveCount may now record a terminal failure.

These run the real handlers against Postgres with the network edges faked.
"""

import json
import re
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from app.core.config import settings
from app.crud import scrape_run as scrape_run_crud
from app.messages import QueueAMessage, QueueBMessage
from app.status import AnalysisStatus, DownloadStatus, ScrapeRunStatus
from lambdas import analysis, discovery, download
from lambdas.common import MAX_RECEIVE_COUNT

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_URL = "https://investors.csl.com/investors/asx-announcements"


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


@pytest.fixture()
def workers_use(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    @contextmanager
    def test_session():
        yield db_session

    for worker in (discovery, download, analysis):
        monkeypatch.setattr(worker, "database_session", test_session)
    return db_session


def _record(body: str, attempt: int) -> dict:
    return {
        "messageId": f"message-{attempt}",
        "body": body,
        "attributes": {"ApproximateReceiveCount": str(attempt)},
    }


def _run_with_one_document(db: Session):
    run, _created = scrape_run_crud.get_or_create_queued_run(
        db,
        ticker="CSL",
        source_url=SOURCE_URL,
        idempotency_key=f"test:{uuid.uuid4()}",
    )
    document_url = f"https://investors.csl.com/pdf/{uuid.uuid4()}.pdf"
    artifact, _created = scrape_run_crud.get_or_create_artifact(
        db,
        scrape_run_id=run.id,
        canonical_url=document_url,
        document_url=document_url,
        source_adapter="csl",
        source_id=f"transient-{uuid.uuid4()}",
        title="CSL half year results",
    )
    scrape_run_crud.mark_run_discovery_started(db, run.id)
    scrape_run_crud.mark_run_discovery_completed(db, run.id, items_found=1)
    return run, artifact


def _download(artifact, run, attempt: int, monkeypatch: pytest.MonkeyPatch) -> None:
    message = QueueBMessage(
        scrape_run_id=run.id,
        artifact_id=artifact.id,
        ticker="CSL",
        source_url=SOURCE_URL,
        document_url=artifact.document_url,
        canonical_url=artifact.canonical_url,
        title=artifact.title,
    )
    monkeypatch.setattr(download.boto3, "client", lambda _service: MagicMock())
    monkeypatch.setattr(
        download,
        "_resolve_download",
        MagicMock(side_effect=TimeoutError("source timed out")),
    )
    with pytest.raises(TimeoutError):
        download.handler({"Records": [_record(message.model_dump_json(), attempt)]}, None)


def test_template_redrive_matches_the_final_attempt() -> None:
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(encoding="utf-8")
    counts = re.findall(r"maxReceiveCount: (\d+)", template)

    assert len(counts) >= 3
    assert {int(count) for count in counts} == {MAX_RECEIVE_COUNT}


def test_retryable_download_failure_leaves_artifact_and_run_open(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, artifact = _run_with_one_document(workers_use)

    _download(artifact, run, 1, monkeypatch)

    workers_use.refresh(artifact)
    workers_use.refresh(run)
    assert artifact.download_status == DownloadStatus.DOWNLOADING
    assert "source timed out" in artifact.last_error
    assert run.items_failed == 0
    assert run.status == ScrapeRunStatus.DOWNLOADING
    assert run.finished_at is None


def test_final_download_attempt_fails_artifact_and_finishes_run(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, artifact = _run_with_one_document(workers_use)

    for attempt in range(1, MAX_RECEIVE_COUNT + 1):
        _download(artifact, run, attempt, monkeypatch)

    workers_use.refresh(artifact)
    workers_use.refresh(run)
    assert artifact.download_status == DownloadStatus.FAILED
    assert run.items_failed == 1
    assert run.status == ScrapeRunStatus.FAILED
    assert run.finished_at is not None


def _analyse(artifact, attempt: int, monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"raw/CSL/{artifact.id}/{'a' * 64}.pdf"
    body = {
        "Records": [
            {
                "eventName": "ObjectCreated:Put",
                "s3": {"bucket": {"name": "raw-documents"}, "object": {"key": key}},
            }
        ]
    }
    monkeypatch.setenv("RAW_DOCUMENT_BUCKET", "raw-documents")
    monkeypatch.setattr(analysis.boto3, "client", lambda _service: MagicMock())
    monkeypatch.setattr(
        analysis,
        "_analyse_object",
        MagicMock(side_effect=ConnectionError("model endpoint reset")),
    )
    with pytest.raises(ConnectionError):
        analysis.handler({"Records": [_record(json.dumps(body), attempt)]}, None)


@pytest.mark.parametrize(
    ("attempt", "expected_status", "expected_failed"),
    [
        (1, AnalysisStatus.ANALYZING, 0),
        (MAX_RECEIVE_COUNT - 1, AnalysisStatus.ANALYZING, 0),
        (MAX_RECEIVE_COUNT, AnalysisStatus.FAILED, 1),
    ],
)
def test_analysis_failure_is_terminal_only_on_the_final_attempt(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
    attempt: int,
    expected_status: str,
    expected_failed: int,
) -> None:
    run, artifact = _run_with_one_document(workers_use)
    scrape_run_crud.mark_artifact_download_started(workers_use, artifact.id)
    scrape_run_crud.mark_artifact_stored(
        workers_use,
        artifact.id,
        checksum_sha256="a" * 64,
        s3_bucket="raw-documents",
        s3_key=f"raw/CSL/{artifact.id}/{'a' * 64}.pdf",
        content_type="application/pdf",
        file_size_bytes=128,
    )
    scrape_run_crud.mark_artifact_analysis_started(workers_use, artifact.id)

    _analyse(artifact, attempt, monkeypatch)

    workers_use.refresh(artifact)
    workers_use.refresh(run)
    assert artifact.analysis_status == expected_status
    assert "model endpoint reset" in artifact.last_error
    assert run.items_failed == expected_failed
    assert (run.finished_at is not None) is (expected_failed == 1)


def test_rerequest_during_discovery_retry_does_not_enqueue_again(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue = MagicMock(return_value="message-id")
    monkeypatch.setattr(main.scrape_queue, "enqueue_discovery", enqueue)
    monkeypatch.setattr(main.settings, "SUPPORTED_TICKERS", ["CSL"])
    request_key = f"retry-{uuid.uuid4()}"

    first = main.scrape_ticker(
        ticker_symbol="CSL",
        idempotency_key=request_key,
        db=workers_use,
    )
    assert enqueue.call_count == 1

    async def unreachable_source(_ticker):
        raise ConnectionError("investor site unreachable")

    monkeypatch.setattr(discovery.scraper_registry, "discover", unreachable_source)
    queue_a = QueueAMessage(
        scrape_run_id=first["scrape_run_id"],
        ticker="CSL",
        source_url=SOURCE_URL,
    )
    with pytest.raises(ConnectionError):
        discovery.handler({"Records": [_record(queue_a.model_dump_json(), 1)]}, None)

    run = scrape_run_crud.get_scrape_run(workers_use, first["scrape_run_id"])
    workers_use.refresh(run)
    assert run.status == ScrapeRunStatus.DISCOVERING
    assert "investor site unreachable" in run.error_message

    again = main.scrape_ticker(
        ticker_symbol="CSL",
        idempotency_key=request_key,
        db=workers_use,
    )

    assert again["scrape_run_id"] == first["scrape_run_id"]
    assert again["status"] == ScrapeRunStatus.DISCOVERING
    assert enqueue.call_count == 1


def test_final_discovery_attempt_fails_the_run(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, _created = scrape_run_crud.get_or_create_queued_run(
        workers_use,
        ticker="CSL",
        source_url=SOURCE_URL,
        idempotency_key=f"test:{uuid.uuid4()}",
    )

    async def unreachable_source(_ticker):
        raise ConnectionError("investor site unreachable")

    monkeypatch.setattr(discovery.scraper_registry, "discover", unreachable_source)
    queue_a = QueueAMessage(scrape_run_id=run.id, ticker="CSL", source_url=SOURCE_URL)
    with pytest.raises(ConnectionError):
        discovery.handler(
            {"Records": [_record(queue_a.model_dump_json(), MAX_RECEIVE_COUNT)]},
            None,
        )

    workers_use.refresh(run)
    assert run.status == ScrapeRunStatus.FAILED
    assert run.finished_at is not None
