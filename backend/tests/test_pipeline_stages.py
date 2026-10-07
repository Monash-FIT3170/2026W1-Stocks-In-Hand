"""The discovery, download and analysis stages, run on Postgres.

Every stage records its outcome the same way (``lambdas.pipeline_stage``):
a permanent error is final, a retryable error records the attempt only, and
the final receive is final. A retryable failure used to record a terminal
FAILED state, and the API or scheduler could then enqueue a second Queue A
message for a run SQS was still redelivering.

These run the real handlers against Postgres with the network edges faked:
the source adapter, SQS and S3.
"""

import hashlib
import json
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from app.core.config import settings
from app.crud import scrape_run as scrape_run_crud
from app.messages import QueueAMessage, QueueBMessage
from app.models.artifact import Artifact
from app.models.scrape_run import ScrapeRun
from app.services import scrape_runs
from app.sources import SOURCES
from app.status import AnalysisStatus, DownloadStatus, ScrapeRunStatus
from lambdas import (
    analysis,
    discovery,
    download,
    pipeline_stage,
    schedule,
    source_download,
)
from lambdas.common import MAX_RECEIVE_COUNT, PermanentDocumentError
from lambdas.download_validation import DownloadedDocument
from scrapers.base import Announcement
from tools.template_model import template_model


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

    for module in (discovery, download, analysis, pipeline_stage):
        monkeypatch.setattr(module, "database_session", test_session)
    return db_session


class FakeSqs:
    def __init__(self) -> None:
        self.bodies: list[str] = []

    def send_message(self, **kwargs) -> dict:
        self.bodies.append(kwargs["MessageBody"])
        return {"MessageId": f"message-{len(self.bodies)}"}

    def queue_b(self) -> list[QueueBMessage]:
        return [QueueBMessage.model_validate_json(body) for body in self.bodies]


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}

    def put_object(self, **kwargs) -> dict:
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs
        return {}

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        if (Bucket, Key) not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )
        return {}


def _record(body: str, attempt: int = 1) -> dict:
    return {
        "messageId": f"message-{attempt}",
        "body": body,
        "attributes": {"ApproximateReceiveCount": str(attempt)},
    }


def _requested_run(db: Session, ticker: str = "CSL", **metadata):
    """Request a run the way the API does, returning it and its Queue A message."""
    sent: list[QueueAMessage] = []
    requested = scrape_runs.request_scrape_run(
        db,
        ticker=ticker,
        idempotency_key=f"test:{uuid.uuid4()}",
        send=sent.append,
        metadata=metadata,
    )
    return scrape_run_crud.get_scrape_run(db, requested.scrape_run_id), sent[0]


def _announcement(ticker: str = "CSL", *, age: timedelta = timedelta(0), **fields):
    now = datetime.now(timezone.utc)
    defaults = {
        "title": "Half year results",
        "pdf_url": f"https://investors.csl.com/pdf/{uuid.uuid4()}.pdf",
        "source_url": SOURCES[ticker].source_url,
    }
    return Announcement(ticker=ticker, date=now - age, **{**defaults, **fields})


def _discover(
    queue_a: QueueAMessage,
    announcements: list[Announcement],
    monkeypatch: pytest.MonkeyPatch,
    *,
    attempt: int = 1,
) -> FakeSqs:
    sqs = FakeSqs()

    async def discover(ticker):
        assert ticker == queue_a.ticker
        return announcements

    monkeypatch.setattr(discovery.scraper_registry, "discover", discover)
    monkeypatch.setattr(discovery.boto3, "client", lambda _service: sqs)
    monkeypatch.setenv("DOWNLOAD_QUEUE_URL", "https://sqs.example/queue-b")
    discovery.handler({"Records": [_record(queue_a.model_dump_json(), attempt)]}, None)
    return sqs


def _run_with_one_document(db: Session):
    run, _queue_a = _requested_run(db)
    document_url = f"https://investors.csl.com/pdf/{uuid.uuid4()}.pdf"
    artifact, _created = scrape_run_crud.get_or_create_artifact(
        db,
        scrape_run_id=run.id,
        canonical_url=document_url,
        document_url=document_url,
        source_adapter="csl",
        source_id=f"stage-{uuid.uuid4()}",
        title="CSL half year results",
    )
    scrape_run_crud.mark_run_discovery_started(db, run.id)
    scrape_run_crud.mark_run_discovery_completed(db, run.id, items_found=1)
    return run, artifact


def _queue_b(artifact, run, **overrides) -> QueueBMessage:
    fields = {
        "scrape_run_id": run.id,
        "artifact_id": artifact.id,
        "ticker": "CSL",
        "source_url": SOURCES["CSL"].source_url,
        "document_url": artifact.document_url,
        "canonical_url": artifact.canonical_url,
        "source_adapter": "csl",
        "title": artifact.title,
    }
    return QueueBMessage(**{**fields, **overrides})


def _download(
    message: QueueBMessage,
    monkeypatch: pytest.MonkeyPatch,
    *,
    resolve,
    s3: FakeS3 | None = None,
    attempt: int = 1,
) -> FakeS3:
    s3 = s3 or FakeS3()

    def client(service):
        assert service == "s3", "the download stage must not send to a queue"
        return s3

    monkeypatch.setattr(download.boto3, "client", client)
    monkeypatch.setattr(source_download, "resolve_download", resolve)
    monkeypatch.setenv("RAW_DOCUMENT_BUCKET", "raw-documents")
    download.handler({"Records": [_record(message.model_dump_json(), attempt)]}, None)
    return s3


def _pdf(content: bytes = b"%PDF-1.7\ncontent"):
    def resolve(message, *, max_bytes):
        return DownloadedDocument(
            content=content,
            checksum=hashlib.sha256(content).hexdigest(),
            final_url=str(message.document_url),
            content_type="application/pdf",
        )

    return resolve


def _failing(error: Exception):
    def resolve(_message, *, max_bytes):
        raise error

    return resolve


def test_template_redrive_matches_the_final_attempt() -> None:
    model = template_model()
    counts = {
        queue_id: model.queue(queue_id).max_receive_count for queue_id in model.consumers()
    }

    assert counts and set(counts.values()) == {MAX_RECEIVE_COUNT}, counts


# Discovery


def test_discovery_queues_each_new_document_once(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, queue_a = _requested_run(workers_use)
    report = _announcement()
    same_link = _announcement(
        title="Same report, tracked link",
        pdf_url=f"{report.pdf_url}?utm_source=newsletter",
        age=timedelta(minutes=1),
    )

    sqs = _discover(queue_a, [report, same_link], monkeypatch)

    [queued] = sqs.queue_b()
    artifact = workers_use.get(Artifact, queued.artifact_id)
    workers_use.refresh(run)
    assert str(queued.document_url) == report.pdf_url
    assert queued.scrape_run_id == run.id
    assert artifact.scrape_run_id == run.id
    assert artifact.source_adapter == "csl"
    assert artifact.download_status == DownloadStatus.PENDING
    assert run.status == ScrapeRunStatus.DOWNLOADING
    assert run.items_found == 1


def test_discovery_queues_recent_documents_newest_first_up_to_the_limit(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, queue_a = _requested_run(workers_use)
    monkeypatch.setenv("MAX_DOCUMENTS_PER_RUN", "3")
    monkeypatch.setenv("DISCOVERY_LOOKBACK_DAYS", "30")
    announcements = [
        _announcement(title=f"Document {index}", age=timedelta(minutes=index))
        for index in (3, 0, 4, 1, 2)
    ] + [_announcement(title="Too old", age=timedelta(days=31))]

    sqs = _discover(queue_a, announcements, monkeypatch)

    workers_use.refresh(run)
    assert [message.title for message in sqs.queue_b()] == [
        "Document 0",
        "Document 1",
        "Document 2",
    ]
    assert run.items_found == 3


def test_discovery_skips_documents_an_earlier_run_already_queued(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _announcement()
    _first_run, first_queue_a = _requested_run(workers_use)
    _discover(first_queue_a, [report], monkeypatch)
    second_run, second_queue_a = _requested_run(workers_use)

    sqs = _discover(second_queue_a, [report], monkeypatch)

    workers_use.refresh(second_run)
    assert sqs.bodies == []
    assert second_run.status == ScrapeRunStatus.COMPLETED
    assert second_run.items_found == 0


def test_redelivered_discovery_requeues_its_documents_without_regressing_the_run(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, queue_a = _requested_run(workers_use)
    report = _announcement()
    [first] = _discover(queue_a, [report], monkeypatch).queue_b()
    # Download has already stored the document when Queue A is redelivered.
    scrape_run_crud.mark_artifact_download_started(workers_use, first.artifact_id)
    scrape_run_crud.mark_artifact_stored(
        workers_use,
        first.artifact_id,
        checksum_sha256="a" * 64,
        s3_bucket="raw-documents",
        s3_key="stored-object",
        content_type="application/pdf",
        file_size_bytes=128,
    )

    [again] = _discover(queue_a, [report], monkeypatch, attempt=2).queue_b()

    workers_use.refresh(run)
    assert again.artifact_id == first.artifact_id
    assert run.status == ScrapeRunStatus.ANALYZING


def test_discovery_carries_the_adapters_resolution_hints_to_download(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run, queue_a = _requested_run(workers_use, "BHP", trigger="eventbridge")
    article_url = f"https://www.bhp.com/news/articles/2026/07/{uuid.uuid4()}"
    announcement = _announcement(
        "BHP",
        pdf_url=article_url,
        metadata={"article_url": article_url, "source_id": article_url},
    )

    [queued] = _discover(queue_a, [announcement], monkeypatch).queue_b()

    artifact = workers_use.get(Artifact, queued.artifact_id)
    assert queued.source_adapter == "bhp"
    assert queued.source_id == article_url
    assert queued.metadata == {
        "trigger": "eventbridge",
        "article_url": article_url,
        "source_id": article_url,
    }
    assert artifact.source_adapter == "bhp"
    assert artifact.source_id == article_url
    assert artifact.artifact_metadata["article_url"] == article_url


def test_discovery_of_another_tickers_document_fails_the_run_at_once(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, queue_a = _requested_run(workers_use)

    sqs = _discover(queue_a, [_announcement("BHP")], monkeypatch)

    workers_use.refresh(run)
    assert sqs.bodies == []
    assert run.status == ScrapeRunStatus.FAILED
    assert run.error_message.startswith("source_identity_mismatch:")


@pytest.mark.parametrize(
    "body",
    [
        "{}",
        QueueAMessage(
            scrape_run_id=uuid.uuid4(),
            ticker="CSL",
            source_url=SOURCES["CSL"].source_url,
            source_adapter="csl",
        ).model_dump_json(),
    ],
    ids=["malformed", "unknown run"],
)
def test_discovery_acknowledges_a_message_it_can_never_process(
    workers_use: Session,
    body: str,
) -> None:
    assert discovery.handler({"Records": [_record(body)]}, None) == {"processed": 1}


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
    queue_a = enqueue.call_args.args[0]
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
    run, queue_a = _requested_run(workers_use)

    async def unreachable_source(_ticker):
        raise ConnectionError("investor site unreachable")

    monkeypatch.setattr(discovery.scraper_registry, "discover", unreachable_source)
    with pytest.raises(ConnectionError):
        discovery.handler(
            {"Records": [_record(queue_a.model_dump_json(), MAX_RECEIVE_COUNT)]},
            None,
        )

    workers_use.refresh(run)
    assert run.status == ScrapeRunStatus.FAILED
    assert run.finished_at is not None


# Download


def test_download_stores_the_document_and_moves_the_run_to_analysis(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, artifact = _run_with_one_document(workers_use)
    content = b"%PDF-1.7\nhalf year results"

    s3 = _download(_queue_b(artifact, run), monkeypatch, resolve=_pdf(content))

    workers_use.refresh(artifact)
    workers_use.refresh(run)
    [((bucket, key), put)] = s3.objects.items()
    assert put["Body"] == content
    assert put["IfNoneMatch"] == "*"
    assert artifact.download_status == DownloadStatus.STORED
    assert (artifact.s3_bucket, artifact.s3_key) == (bucket, key)
    assert artifact.checksum_sha256 == hashlib.sha256(content).hexdigest()
    assert run.status == ScrapeRunStatus.ANALYZING
    assert run.items_downloaded == 1


def test_download_of_a_stored_document_is_skipped(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, artifact = _run_with_one_document(workers_use)
    message = _queue_b(artifact, run)
    s3 = _download(message, monkeypatch, resolve=_pdf())

    _download(
        message,
        monkeypatch,
        resolve=_failing(AssertionError("stored document was downloaded again")),
        s3=s3,
        attempt=2,
    )

    workers_use.refresh(run)
    assert run.items_downloaded == 1


def test_permanent_download_error_fails_the_artifact_on_the_first_receive(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, artifact = _run_with_one_document(workers_use)
    gone = PermanentDocumentError("Document no longer exists", code="document_not_found")

    _download(_queue_b(artifact, run), monkeypatch, resolve=_failing(gone))

    workers_use.refresh(artifact)
    workers_use.refresh(run)
    assert artifact.download_status == DownloadStatus.FAILED
    assert artifact.last_error.startswith("document_not_found:")
    assert run.items_failed == 1
    assert run.status == ScrapeRunStatus.FAILED


def test_download_for_a_mismatched_artifact_is_not_recorded_against_it(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, artifact = _run_with_one_document(workers_use)
    other_url = f"https://investors.csl.com/pdf/{uuid.uuid4()}.pdf"
    message = _queue_b(artifact, run, document_url=other_url, canonical_url=other_url)

    _download(message, monkeypatch, resolve=_pdf())

    workers_use.refresh(artifact)
    assert artifact.download_status == DownloadStatus.PENDING
    assert artifact.last_error is None


def test_retryable_download_failure_leaves_artifact_and_run_open(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, artifact = _run_with_one_document(workers_use)

    with pytest.raises(TimeoutError):
        _download(
            _queue_b(artifact, run),
            monkeypatch,
            resolve=_failing(TimeoutError("source timed out")),
        )

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
        with pytest.raises(TimeoutError):
            _download(
                _queue_b(artifact, run),
                monkeypatch,
                resolve=_failing(TimeoutError("source timed out")),
                attempt=attempt,
            )

    workers_use.refresh(artifact)
    workers_use.refresh(run)
    assert artifact.download_status == DownloadStatus.FAILED
    assert run.items_failed == 1
    assert run.status == ScrapeRunStatus.FAILED
    assert run.finished_at is not None


# Analysis


def _s3_event(artifact, *, bucket: str = "raw-documents") -> str:
    key = f"raw/CSL/{artifact.id}/{'a' * 64}.pdf"
    return json.dumps(
        {
            "Records": [
                {
                    "eventName": "ObjectCreated:Put",
                    "s3": {"bucket": {"name": bucket}, "object": {"key": key}},
                }
            ]
        }
    )


def _analyse(body: str, attempt: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAW_DOCUMENT_BUCKET", "raw-documents")
    monkeypatch.setattr(analysis.boto3, "client", lambda _service: MagicMock())
    monkeypatch.setattr(
        analysis,
        "_analyse_object",
        MagicMock(side_effect=ConnectionError("model endpoint reset")),
    )
    analysis.handler({"Records": [_record(body, attempt)]}, None)


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

    with pytest.raises(ConnectionError):
        _analyse(_s3_event(artifact), attempt, monkeypatch)

    workers_use.refresh(artifact)
    workers_use.refresh(run)
    assert artifact.analysis_status == expected_status
    assert "model endpoint reset" in artifact.last_error
    assert run.items_failed == expected_failed
    assert (run.finished_at is not None) is (expected_failed == 1)


def test_analysis_event_from_another_bucket_is_not_recorded_against_the_artifact(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run, artifact = _run_with_one_document(workers_use)

    _analyse(_s3_event(artifact, bucket="someone-elses-bucket"), 1, monkeypatch)

    workers_use.refresh(artifact)
    assert artifact.analysis_status == AnalysisStatus.PENDING
    assert artifact.last_error is None


def test_stored_text_without_text_fails_its_analysis_at_once(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = Artifact(
        source_type="reddit",
        artifact_type="reddit_post",
        title="",
        raw_text="",
        content_hash=f"reddit:{uuid.uuid4()}",
    )
    workers_use.add(artifact)
    workers_use.commit()
    body = json.dumps(
        {"message_type": "public_discussion_analysis", "artifact_id": str(artifact.id)}
    )

    analysis.handler({"Records": [_record(body)]}, None)

    workers_use.refresh(artifact)
    assert artifact.analysis_status == AnalysisStatus.FAILED
    assert artifact.last_error.startswith("no_extractable_text:")


# Abandoned work: a Lambda that times out on the final receive records nothing.


def _age(db: Session, model, row_id, **columns) -> None:
    db.query(model).filter(model.id == row_id).update(columns)
    db.commit()


def test_work_left_open_past_the_redelivery_window_is_failed(
    workers_use: Session,
) -> None:
    long_ago = datetime.now(timezone.utc) - timedelta(days=2)
    downloading_run, downloading = _run_with_one_document(workers_use)
    scrape_run_crud.mark_artifact_download_started(workers_use, downloading.id)
    _age(workers_use, Artifact, downloading.id, updated_at=long_ago)
    discovering_run, _queue_a = _requested_run(workers_use)
    scrape_run_crud.mark_run_discovery_started(workers_use, discovering_run.id)
    _age(workers_use, ScrapeRun, discovering_run.id, started_at=long_ago)
    stored_text = Artifact(
        source_type="reddit",
        artifact_type="reddit_post",
        title="ASX chatter",
        raw_text="CSL looks strong",
        content_hash=f"reddit:{uuid.uuid4()}",
        analysis_status=AnalysisStatus.ANALYZING,
    )
    workers_use.add(stored_text)
    workers_use.commit()
    _age(workers_use, Artifact, stored_text.id, updated_at=long_ago)

    closed = scrape_run_crud.fail_abandoned_work(
        workers_use, older_than=schedule.ABANDONED_AFTER
    )

    for row in (downloading_run, downloading, discovering_run, stored_text):
        workers_use.refresh(row)
    assert closed == {"runs": 1, "downloads": 1, "analyses": 1}
    assert downloading.download_status == DownloadStatus.FAILED
    assert downloading.last_error == scrape_run_crud.ABANDONED_ERROR
    assert downloading_run.status == ScrapeRunStatus.FAILED
    assert discovering_run.status == ScrapeRunStatus.FAILED
    assert stored_text.analysis_status == AnalysisStatus.FAILED


def test_work_still_inside_the_redelivery_window_stays_open(
    workers_use: Session,
) -> None:
    run, artifact = _run_with_one_document(workers_use)
    scrape_run_crud.mark_artifact_download_started(workers_use, artifact.id)
    scrape_run_crud.record_artifact_download_retry(
        workers_use, artifact.id, error="TimeoutError: source timed out"
    )

    closed = scrape_run_crud.fail_abandoned_work(
        workers_use, older_than=schedule.ABANDONED_AFTER
    )

    workers_use.refresh(artifact)
    workers_use.refresh(run)
    assert closed == {"runs": 0, "downloads": 0, "analyses": 0}
    assert artifact.download_status == DownloadStatus.DOWNLOADING
    assert run.status == ScrapeRunStatus.DOWNLOADING


def test_a_redriven_message_completes_abandoned_work(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, artifact = _run_with_one_document(workers_use)
    scrape_run_crud.mark_artifact_download_started(workers_use, artifact.id)
    scrape_run_crud.fail_abandoned_work(workers_use, older_than=timedelta(0))

    _download(_queue_b(artifact, run), monkeypatch, resolve=_pdf())

    workers_use.refresh(artifact)
    workers_use.refresh(run)
    assert artifact.download_status == DownloadStatus.STORED
    assert run.items_failed == 0
    assert run.status == ScrapeRunStatus.ANALYZING


def test_schedule_fails_abandoned_work_before_requesting_runs(
    workers_use: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, _queue_a = _requested_run(workers_use)
    scrape_run_crud.mark_run_discovery_started(workers_use, run.id)
    _age(
        workers_use,
        ScrapeRun,
        run.id,
        started_at=datetime.now(timezone.utc) - timedelta(days=2),
    )

    @contextmanager
    def test_session():
        yield workers_use

    monkeypatch.setenv("SCHEDULED_TICKERS", "")
    monkeypatch.setenv("DISCOVERY_QUEUE_URL", "https://sqs.example/queue-a")
    monkeypatch.setenv("MARKETAUX_ENABLED", "false")
    monkeypatch.setattr(schedule, "load_runtime_configuration", lambda: None)
    monkeypatch.setattr(schedule, "database_session", test_session)
    monkeypatch.setattr(schedule.boto3, "client", lambda _service: FakeSqs())

    schedule.handler({"id": f"scheduled-{uuid.uuid4()}"}, None)

    workers_use.refresh(run)
    assert run.status == ScrapeRunStatus.FAILED
    assert run.error_message == scrape_run_crud.ABANDONED_ERROR


def test_abandoned_work_waits_out_every_queue_redelivery_window() -> None:
    model = template_model()
    windows = {
        queue_id: timedelta(
            seconds=model.queue(queue_id).visibility_timeout
            * model.queue(queue_id).max_receive_count
        )
        for queue_id in model.consumers()
    }

    assert windows and all(
        window < schedule.ABANDONED_AFTER for window in windows.values()
    ), windows
