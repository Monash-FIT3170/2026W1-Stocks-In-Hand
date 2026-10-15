"""Tests for the database-backed announcements feed.

Each item is the artifact card (``app/services/artifact_card.py``), which
``test_artifact_card.py`` covers.
"""

import sys
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.api.routes import announcement as announcement_routes
from app.core.config import settings
from app.crud.announcement import (
    _sydney_date_end,
    _sydney_date_start,
    _sydney_day_bounds,
    get_announcements,
)
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.services import artifact_summary


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


def test_announcements_route_accepts_path_without_trailing_slash(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(announcement_routes.router)
    app.dependency_overrides[announcement_routes.get_db] = lambda: None
    monkeypatch.setattr(announcement_routes.crud, "get_announcements", lambda *_args, **_kwargs: [])

    response = TestClient(app).get("/announcements", follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == []


def test_the_feed_shows_a_recorded_summary_and_no_lines_without_one(
    db_session: Session,
) -> None:
    ticker = Ticker(
        symbol=f"F{uuid.uuid4().hex[:8].upper()}",
        company_name="Feed Test Limited",
        exchange="ASX",
    )
    db_session.add(ticker)
    db_session.flush()

    def announcement(**values) -> Artifact:
        return Artifact(
            ticker_id=ticker.id,
            source_type="asx_announcement",
            published_at=datetime(2040, 1, 2, 10, 0, tzinfo=timezone.utc),
            content_hash=f"feed-{uuid.uuid4()}",
            **values,
        )

    summarised = announcement(
        artifact_type="dividend_announcement",
        title="Dividend update",
        raw_text="Dividend announcement body",
        artifact_metadata={"category": "DividendAnnouncement"},
    )
    unsummarised = announcement(
        artifact_type="asx_announcement_other",
        title="General update",
        raw_text="Raw filing text that is not a summary.",
    )
    db_session.add_all([summarised, unsummarised])
    db_session.flush()
    artifact_summary.record(
        db_session,
        summarised,
        artifact_summary.from_answer(
            {
                "summary": "The company confirmed its dividend timetable.",
                "about": "Dividend details for shareholders.",
                "changed": "The declared dividend increased.",
                "matters": "This affects shareholder income expectations.",
            },
            model="bedrock:test-model",
            prompt_version="llm-announcement-summary-v3",
        ),
    )
    db_session.commit()

    feed = {
        item.id: item
        for item in get_announcements(
            db_session,
            start_date=date(2040, 1, 1),
            end_date=date(2040, 1, 3),
        )
    }

    assert feed[summarised.id].ticker == ticker.symbol
    assert feed[summarised.id].tag == "Dividend Announcement"
    assert (
        feed[summarised.id].about,
        feed[summarised.id].changed,
        feed[summarised.id].matters,
    ) == (
        "Dividend details for shareholders.",
        "The declared dividend increased.",
        "This affects shareholder income expectations.",
    )
    assert (
        feed[unsummarised.id].about,
        feed[unsummarised.id].changed,
        feed[unsummarised.id].matters,
    ) == (None, None, None)


def test_sydney_day_bounds_match_melbourne_calendar_day() -> None:
    now = datetime(2026, 5, 16, 14, 30, tzinfo=timezone.utc)

    start, end = _sydney_day_bounds(now)

    assert start.isoformat() == "2026-05-17T00:00:00+10:00"
    assert end.isoformat() == "2026-05-18T00:00:00+10:00"


def test_custom_date_bounds_use_sydney_calendar_days() -> None:
    start = _sydney_date_start(date(2026, 5, 1))
    end = _sydney_date_end(date(2026, 5, 16))

    assert start.isoformat() == "2026-05-01T00:00:00+10:00"
    assert end.isoformat() == "2026-05-17T00:00:00+10:00"


def test_announcement_feed_uses_stable_secondary_id_ordering() -> None:
    class QueryStub:
        def __init__(self) -> None:
            self.ordering = ()

        def options(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def order_by(self, *ordering):
            self.ordering = ordering
            return self

        def offset(self, _offset):
            return self

        def limit(self, _limit):
            return self

        def all(self):
            return []

    class DbStub:
        def __init__(self) -> None:
            self.query_stub = QueryStub()

        def query(self, _model):
            return self.query_stub

    db = DbStub()

    assert get_announcements(db) == []
    assert len(db.query_stub.ordering) == 2
    assert str(db.query_stub.ordering[1]) == "artifacts.id DESC"
