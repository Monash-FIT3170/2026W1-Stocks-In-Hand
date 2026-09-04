from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.core.config import settings
from app.crud import scrape_run as scrape_run_crud
from lambdas import public_discussion_schedule as schedule


@contextmanager
def _database_session(db):
    yield db


def _spec(*, source: str = "bluesky", runner=None):
    return schedule.CollectorSpec(
        source=source,
        target="ASX",
        source_url=f"https://{source}.example/search",
        platform_factory=MagicMock(return_value=SimpleNamespace(id=uuid4())),
        runner=runner or MagicMock(),
        arguments=("ASX", 10),
    )


def test_schedule_defaults_to_bounded_keyless_sources(monkeypatch) -> None:
    monkeypatch.setenv(
        "SCHEDULED_PUBLIC_DISCUSSION_SOURCES",
        "reddit,bluesky,mastodon,blog,unknown",
    )
    monkeypatch.setenv("PUBLIC_DISCUSSION_PER_SOURCE_LIMIT", "500")
    with patch.object(settings, "REDDIT_CLIENT_ID", ""), patch.object(
        settings,
        "REDDIT_CLIENT_SECRET",
        "",
    ), patch.object(settings, "PUBLIC_DISCUSSION_FEED_URLS", []):
        specs = schedule._collector_specs()

    assert [spec.source for spec in specs] == ["bluesky", "mastodon"]
    assert all(spec.arguments[-1] == 25 for spec in specs)


def test_schedule_duplicate_completed_run_is_skipped() -> None:
    db = MagicMock()
    runner = MagicMock()
    spec = _spec(runner=runner)
    run = SimpleNamespace(id=uuid4(), status="completed")

    with patch.object(
        schedule,
        "database_session",
        side_effect=lambda: _database_session(db),
    ), patch.object(
        scrape_run_crud,
        "get_or_create_public_discussion_run",
        return_value=(run, False),
    ):
        outcome = schedule._run_collector(spec, "event-1")

    assert outcome == "skipped"
    runner.assert_not_called()


def test_schedule_records_worker_outcome() -> None:
    db = MagicMock()
    runner = MagicMock()
    spec = _spec(source="mastodon", runner=runner)
    run_id = uuid4()
    queued_run = SimpleNamespace(id=run_id, status="queued")
    completed_run = SimpleNamespace(id=run_id, status="completed")

    with patch.object(
        schedule,
        "database_session",
        side_effect=lambda: _database_session(db),
    ), patch.object(
        scrape_run_crud,
        "get_or_create_public_discussion_run",
        return_value=(queued_run, True),
    ) as create_run, patch.object(
        scrape_run_crud,
        "get_scrape_run",
        return_value=completed_run,
    ):
        outcome = schedule._run_collector(spec, "event-1")

    assert outcome == "completed"
    assert create_run.call_args.kwargs["trigger_type"] == "scheduled"
    runner.assert_called_once_with("ASX", 10, run_id)


def test_schedule_handler_counts_each_source_outcome() -> None:
    specs = [_spec(source=name) for name in ("bluesky", "mastodon")]
    with patch.object(schedule, "load_runtime_configuration"), patch.object(
        schedule,
        "_collector_specs",
        return_value=specs,
    ), patch.object(
        schedule,
        "_run_collector",
        side_effect=["completed", "skipped"],
    ):
        result = schedule.handler({"id": "event-1"}, None)

    assert result == {
        "event_id": "event-1",
        "collectors": 2,
        "completed": 1,
        "failed": 0,
        "skipped": 1,
    }


def test_schedule_handler_raises_to_trigger_eventbridge_retry() -> None:
    with patch.object(schedule, "load_runtime_configuration"), patch.object(
        schedule,
        "_collector_specs",
        return_value=[_spec(source="bluesky")],
    ), patch.object(schedule, "_run_collector", return_value="failed"):
        with pytest.raises(RuntimeError, match="1 public discussion collectors failed"):
            schedule.handler({"id": "event-1"}, None)
