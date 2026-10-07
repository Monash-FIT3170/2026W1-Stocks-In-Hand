from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.services import marketaux
from lambdas import schedule


@contextmanager
def _database_session():
    yield MagicMock()


def test_schedule_defaults_to_the_catalogue_scheduled_tickers(monkeypatch) -> None:
    monkeypatch.delenv("SCHEDULED_TICKERS", raising=False)

    assert schedule._enabled_tickers() == ["ANZ", "BHP", "CBA", "CSL", "WES"]


def test_schedule_ignores_tickers_outside_the_catalogue(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULED_TICKERS", "wes, XYZ,anz")

    assert schedule._enabled_tickers() == ["ANZ", "WES"]


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


@contextmanager
def _unavailable_database():
    raise ConnectionError("database unavailable")
    yield  # pragma: no cover


def test_schedule_raises_when_marketaux_collection_fails(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULED_TICKERS", "")
    monkeypatch.setenv("DISCOVERY_QUEUE_URL", "https://sqs.example/queue-a")

    with (
        patch.object(schedule, "load_runtime_configuration"),
        # The abandoned-work check fails quietly and scheduling carries on.
        patch.object(schedule, "database_session", _unavailable_database),
        patch.object(schedule.boto3, "client", return_value=MagicMock()),
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
