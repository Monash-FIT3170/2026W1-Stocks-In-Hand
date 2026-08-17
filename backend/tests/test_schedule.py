from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.crud import scrape_run as scrape_run_crud
from app.messages import QueueAMessage
from app.status import ScrapeRunStatus
from lambdas import schedule


@contextmanager
def _database_session():
    yield MagicMock()


def test_schedule_enqueues_each_enabled_ticker_once(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULED_TICKERS", "CSL,ANZ")
    monkeypatch.setenv("DISCOVERY_QUEUE_URL", "https://sqs.example/queue-a")
    sqs = MagicMock()

    def create_run(_db, *, ticker, **_kwargs):
        return SimpleNamespace(id=uuid4(), status=ScrapeRunStatus.ENQUEUEING, ticker=ticker), True

    with (
        patch.object(schedule, "load_runtime_configuration"),
        patch.object(schedule, "database_session", _database_session),
        patch.object(schedule.boto3, "client", return_value=sqs),
        patch.object(
            scrape_run_crud,
            "get_or_create_queued_run",
            side_effect=create_run,
        ),
        patch.object(scrape_run_crud, "mark_run_queued_if_enqueueing"),
    ):
        result = schedule.handler({"id": "scheduled-event-1"}, None)

    assert result == {"queued": 2, "event_id": "scheduled-event-1"}
    assert sqs.send_message.call_count == 2
    messages = [
        QueueAMessage.model_validate_json(call.kwargs["MessageBody"])
        for call in sqs.send_message.call_args_list
    ]
    assert {message.ticker for message in messages} == {"ANZ", "CSL"}
    assert all(message.metadata == {"trigger": "eventbridge"} for message in messages)


def test_schedule_duplicate_completed_run_is_not_queued() -> None:
    sqs = MagicMock()
    run = SimpleNamespace(id=uuid4(), status=ScrapeRunStatus.COMPLETED)

    with (
        patch.object(schedule, "database_session", _database_session),
        patch.object(
            scrape_run_crud,
            "get_or_create_queued_run",
            return_value=(run, False),
        ),
    ):
        queued = schedule._enqueue_ticker(
            ticker="CSL",
            event_key="scheduled-event-1",
            sqs=sqs,
            queue_url="https://sqs.example/queue-a",
        )

    assert queued is False
    sqs.send_message.assert_not_called()
