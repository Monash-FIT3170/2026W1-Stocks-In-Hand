"""The scheduled public discussion collector, on Postgres with fake fetches."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.scrape_run import ScrapeRun
from app.services.discussion_sources.blog import BLOG
from app.services.discussion_sources.bluesky import BLUESKY
from lambdas import public_discussion_schedule as schedule


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
def scheduled(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    @contextmanager
    def test_session():
        yield db_session

    monkeypatch.setattr(schedule, "load_runtime_configuration", lambda: None)
    monkeypatch.setattr(schedule, "database_session", test_session)
    monkeypatch.setattr(settings, "ANALYSIS_QUEUE_URL", "")
    monkeypatch.setenv("SCHEDULED_PUBLIC_DISCUSSION_SOURCES", "bluesky")
    return db_session


def _bluesky_posts(count: int) -> list[dict]:
    return [
        {
            "uri": f"at://x/{uuid.uuid4().hex}",
            "text": "ASX open",
            "created_at": "2026-10-07T00:00:00Z",
            "author": "investor.test",
        }
        for _ in range(count)
    ]


def _runs(db: Session, event_id: str) -> list[ScrapeRun]:
    return (
        db.query(ScrapeRun)
        .filter(ScrapeRun.idempotency_key.like(f"public-discussion-schedule:{event_id}:%"))
        .all()
    )


def test_schedule_defaults_to_bounded_keyless_sources(monkeypatch) -> None:
    monkeypatch.setenv(
        "SCHEDULED_PUBLIC_DISCUSSION_SOURCES",
        "reddit,bluesky,mastodon,blog,unknown",
    )
    monkeypatch.setenv("PUBLIC_DISCUSSION_PER_SOURCE_LIMIT", "500")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_ID", "")
    monkeypatch.setattr(settings, "REDDIT_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "PUBLIC_DISCUSSION_FEED_URLS", [])

    collections = schedule._collections()

    assert [item.source.source_type for item in collections] == ["bluesky", "mastodon"]
    assert all(item.limit == 25 for item in collections)


def test_schedule_collects_each_source_once_per_event(
    scheduled: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(BLUESKY, "fetch", lambda _target, _limit: _bluesky_posts(2))
    event_id = f"event-{uuid.uuid4()}"

    first = schedule.handler({"id": event_id}, None)
    repeat = schedule.handler({"id": event_id}, None)

    [run] = _runs(scheduled, event_id)
    assert first == {
        "event_id": event_id,
        "collectors": 1,
        "completed": 1,
        "failed": 0,
        "skipped": 0,
    }
    assert repeat["skipped"] == 1
    assert run.trigger_type == "scheduled"
    assert run.status == "completed"
    assert run.items_saved == 2


def test_a_failed_collection_fails_the_event_for_eventbridge_to_retry(
    scheduled: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(_target, _limit):
        raise ConnectionError("AppView unreachable")

    monkeypatch.setattr(BLUESKY, "fetch", unreachable)
    event_id = f"event-{uuid.uuid4()}"

    with pytest.raises(RuntimeError, match="1 public discussion collectors failed"):
        schedule.handler({"id": event_id}, None)

    [run] = _runs(scheduled, event_id)
    assert run.status == "failed"


def test_a_configured_target_its_source_rejects_counts_as_failed(
    scheduled: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHEDULED_PUBLIC_DISCUSSION_SOURCES", "blog")
    monkeypatch.setattr(settings, "PUBLIC_DISCUSSION_FEED_URLS", ["http://insecure.test/feed"])
    monkeypatch.setattr(BLOG, "fetch", lambda _target, _limit: [])

    with pytest.raises(RuntimeError, match="1 public discussion collectors failed"):
        schedule.handler({"id": f"event-{uuid.uuid4()}"}, None)
