"""Requesting a scrape run, on Postgres with a fake Queue A sender.

The API route and the EventBridge schedule both go through
``app.services.scrape_runs.request_scrape_run``.
"""

import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from app.core.config import settings
from app.crud import scrape_run as scrape_run_crud
from app.messages import QueueAMessage
from app.models.scrape_run import ScrapeRun
from app.services import scrape_runs
from app.sources import SOURCES
from app.status import ScrapeRunStatus
from lambdas import schedule


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


class FakeSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[QueueAMessage] = []

    def __call__(self, message: QueueAMessage) -> str:
        if self.error is not None:
            raise self.error
        self.sent.append(message)
        return f"message-{len(self.sent)}"


def _key() -> str:
    return f"test:{uuid.uuid4()}"


def test_request_queues_discovery_from_the_catalogue_source(db_session: Session) -> None:
    sender = FakeSender()

    requested = scrape_runs.request_scrape_run(
        db_session,
        ticker="ANZ",
        idempotency_key=_key(),
        send=sender,
    )

    assert requested.enqueued is True
    assert requested.status == ScrapeRunStatus.QUEUED
    [message] = sender.sent
    assert message.scrape_run_id == requested.scrape_run_id
    assert message.ticker == "ANZ"
    assert message.source_adapter == SOURCES["ANZ"].adapter
    assert str(message.source_url) == SOURCES["ANZ"].source_url
    assert message.metadata == {}
    run = scrape_run_crud.get_scrape_run(db_session, requested.scrape_run_id)
    assert run.status == ScrapeRunStatus.QUEUED
    assert run.source_url == SOURCES["ANZ"].source_url
    assert run.trigger_type == "manual"
    assert run.queued_at is not None


def test_repeat_request_for_an_active_run_does_not_send_again(
    db_session: Session,
) -> None:
    sender = FakeSender()
    key = _key()
    first = scrape_runs.request_scrape_run(
        db_session, ticker="CSL", idempotency_key=key, send=sender
    )
    scrape_run_crud.mark_run_discovery_started(db_session, first.scrape_run_id)

    again = scrape_runs.request_scrape_run(
        db_session, ticker="CSL", idempotency_key=key, send=sender
    )

    assert again.scrape_run_id == first.scrape_run_id
    assert again.status == ScrapeRunStatus.DISCOVERING
    assert again.enqueued is False
    assert len(sender.sent) == 1


def test_failed_send_fails_the_run_and_a_repeat_sends_again(
    db_session: Session,
) -> None:
    key = _key()

    with pytest.raises(scrape_runs.DiscoveryEnqueueError):
        scrape_runs.request_scrape_run(
            db_session,
            ticker="CSL",
            idempotency_key=key,
            send=FakeSender(error=RuntimeError("SQS unavailable")),
        )

    [run] = (
        db_session.query(ScrapeRun)
        .filter_by(idempotency_key=key)
        .all()
    )
    assert run.status == ScrapeRunStatus.FAILED
    assert run.error_message == scrape_runs.ENQUEUE_FAILED

    sender = FakeSender()
    again = scrape_runs.request_scrape_run(
        db_session, ticker="CSL", idempotency_key=key, send=sender
    )

    db_session.refresh(run)
    assert again.scrape_run_id == run.id
    assert again.enqueued is True
    assert len(sender.sent) == 1
    assert run.status == ScrapeRunStatus.QUEUED
    assert run.error_message is None


def test_request_left_before_its_send_is_sent_again(db_session: Session) -> None:
    key = _key()
    # A producer that crashed between recording the run and sending Queue A.
    run, _created = scrape_run_crud.get_or_create_queued_run(
        db_session,
        ticker="CSL",
        source_url=SOURCES["CSL"].source_url,
        idempotency_key=key,
    )
    sender = FakeSender()

    requested = scrape_runs.request_scrape_run(
        db_session, ticker="CSL", idempotency_key=key, send=sender
    )

    assert requested.scrape_run_id == run.id
    assert requested.enqueued is True
    assert len(sender.sent) == 1


def test_ticker_outside_the_catalogue_creates_no_run(db_session: Session) -> None:
    sender = FakeSender()
    key = _key()

    with pytest.raises(ValueError, match="XYZ"):
        scrape_runs.request_scrape_run(
            db_session, ticker="XYZ", idempotency_key=key, send=sender
        )

    assert sender.sent == []
    assert (
        db_session.query(ScrapeRun)
        .filter_by(idempotency_key=key)
        .count()
        == 0
    )


def test_scheduled_request_records_its_trigger(db_session: Session) -> None:
    sender = FakeSender()

    requested = scrape_runs.request_scrape_run(
        db_session,
        ticker="wes",
        idempotency_key=_key(),
        send=sender,
        trigger_type="scheduled",
        metadata={"trigger": "eventbridge"},
    )

    [message] = sender.sent
    assert message.ticker == "WES"
    assert message.metadata == {"trigger": "eventbridge"}
    run = scrape_run_crud.get_scrape_run(db_session, requested.scrape_run_id)
    assert run.trigger_type == "scheduled"


def test_scrape_route_returns_the_queued_run(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = FakeSender()
    monkeypatch.setattr(main.scrape_queue, "enqueue_discovery", sender)
    monkeypatch.setattr(main.settings, "SUPPORTED_TICKERS", ["CSL"])
    request_key = f"browser-{uuid.uuid4()}"

    result = main.scrape_ticker(
        ticker_symbol="csl.ax",
        idempotency_key=request_key,
        db=db_session,
    )

    assert result["status"] == ScrapeRunStatus.QUEUED
    assert result["ticker"] == "CSL"
    run = scrape_run_crud.get_scrape_run(db_session, result["scrape_run_id"])
    assert run.idempotency_key == f"scrape:CSL:{request_key}"
    assert [message.scrape_run_id for message in sender.sent] == [run.id]


def test_scrape_route_answers_503_when_discovery_cannot_be_queued(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main.scrape_queue,
        "enqueue_discovery",
        FakeSender(error=RuntimeError("SQS unavailable")),
    )
    monkeypatch.setattr(main.settings, "SUPPORTED_TICKERS", ["CSL"])

    with pytest.raises(HTTPException) as exc_info:
        main.scrape_ticker(
            ticker_symbol="CSL",
            idempotency_key=f"failed-{uuid.uuid4()}",
            db=db_session,
        )

    assert exc_info.value.status_code == 503


def test_schedule_requests_each_enabled_ticker_once_per_event(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def test_session():
        yield db_session

    sqs = MagicMock()
    monkeypatch.setenv("SCHEDULED_TICKERS", "CSL,ANZ")
    monkeypatch.setenv("DISCOVERY_QUEUE_URL", "https://sqs.example/queue-a")
    monkeypatch.setenv("MARKETAUX_ENABLED", "false")
    monkeypatch.setattr(schedule, "load_runtime_configuration", lambda: None)
    monkeypatch.setattr(schedule, "database_session", test_session)
    monkeypatch.setattr(schedule.boto3, "client", lambda _service: sqs)
    event = {"id": f"scheduled-{uuid.uuid4()}"}

    first = schedule.handler(event, None)
    repeat = schedule.handler(event, None)

    assert first["queued"] == 2
    assert repeat["queued"] == 0
    messages = [
        QueueAMessage.model_validate_json(call.kwargs["MessageBody"])
        for call in sqs.send_message.call_args_list
    ]
    assert {message.ticker for message in messages} == {"ANZ", "CSL"}
    assert all(message.metadata == {"trigger": "eventbridge"} for message in messages)
    assert {
        call.kwargs["QueueUrl"] for call in sqs.send_message.call_args_list
    } == {"https://sqs.example/queue-a"}
