from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.crud import scrape_run as scrape_run_crud
from app.messages import QueueAMessage
from app.services import marketaux
from lambdas import schedule


@contextmanager
def _database_session():
    yield MagicMock()


def test_schedule_enqueues_each_enabled_ticker_once(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULED_TICKERS", "CSL,ANZ")
    monkeypatch.setenv("DISCOVERY_QUEUE_URL", "https://sqs.example/queue-a")
    sqs = MagicMock()

    def create_run(_db, *, ticker, **_kwargs):
        return SimpleNamespace(id=uuid4(), status="enqueueing", ticker=ticker), True

    with (
        patch.object(schedule, "load_runtime_configuration"),
        patch.object(schedule, "database_session", _database_session),
        patch.object(
            schedule,
            "_collect_marketaux_news",
            return_value={
                "marketaux_tickers": 0,
                "marketaux_created": 0,
                "marketaux_analysis_queued": 0,
                "marketaux_errors": 0,
            },
        ),
        patch.object(schedule.boto3, "client", return_value=sqs),
        patch.object(
            scrape_run_crud,
            "get_or_create_queued_run",
            side_effect=create_run,
        ),
        patch.object(scrape_run_crud, "mark_run_queued_if_enqueueing"),
    ):
        result = schedule.handler({"id": "scheduled-event-1"}, None)

    assert result == {
        "queued": 2,
        "event_id": "scheduled-event-1",
        "marketaux_tickers": 0,
        "marketaux_created": 0,
        "marketaux_analysis_queued": 0,
        "marketaux_errors": 0,
    }
    assert sqs.send_message.call_count == 2
    messages = [
        QueueAMessage.model_validate_json(call.kwargs["MessageBody"])
        for call in sqs.send_message.call_args_list
    ]
    assert {message.ticker for message in messages} == {"ANZ", "CSL"}
    assert all(message.metadata == {"trigger": "eventbridge"} for message in messages)


def test_schedule_duplicate_completed_run_is_not_queued() -> None:
    sqs = MagicMock()
    run = SimpleNamespace(id=uuid4(), status="completed")

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


def test_marketaux_schedule_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("MARKETAUX_ENABLED", "true")
    monkeypatch.setenv("MARKETAUX_PER_TICKER_LIMIT", "999")
    tickers = ["ANZ", "BHP", "CBA", "COH", "COL", "CSL", "MQG"]

    with (
        patch.object(schedule, "database_session", _database_session),
        patch.object(
            marketaux,
            "fetch_and_store_news",
            return_value={"created": 1, "analysis_queued": 1, "errors": 0},
        ) as collect,
    ):
        result = schedule._collect_marketaux_news(tickers)

    assert result == {
        "marketaux_tickers": 5,
        "marketaux_created": 5,
        "marketaux_analysis_queued": 5,
        "marketaux_errors": 0,
    }
    assert [call.args[0] for call in collect.call_args_list] == tickers[:5]
    assert all(call.args[1] == 25 for call in collect.call_args_list)
    assert all(
        call.kwargs == {"summarise": False, "enqueue_analysis": True}
        for call in collect.call_args_list
    )


def test_marketaux_schedule_skips_collection_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MARKETAUX_ENABLED", "false")

    with patch.object(marketaux, "fetch_and_store_news") as collect:
        result = schedule._collect_marketaux_news(["ANZ"])

    assert result == {
        "marketaux_tickers": 0,
        "marketaux_created": 0,
        "marketaux_analysis_queued": 0,
        "marketaux_errors": 0,
    }
    collect.assert_not_called()


def test_schedule_raises_when_marketaux_collection_fails(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULED_TICKERS", "ANZ")
    monkeypatch.setenv("DISCOVERY_QUEUE_URL", "https://sqs.example/queue-a")

    with (
        patch.object(schedule, "load_runtime_configuration"),
        patch.object(schedule.boto3, "client", return_value=MagicMock()),
        patch.object(schedule, "_enqueue_ticker", return_value=False),
        patch.object(
            schedule,
            "_collect_marketaux_news",
            return_value={
                "marketaux_tickers": 1,
                "marketaux_created": 0,
                "marketaux_analysis_queued": 0,
                "marketaux_errors": 1,
            },
        ),
    ):
        with pytest.raises(RuntimeError, match="Marketaux collection failed"):
            schedule.handler({"id": "scheduled-event-1"}, None)
