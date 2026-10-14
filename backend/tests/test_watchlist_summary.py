"""The watchlist page's one read, on Postgres.

The page used to fetch the investor's watchlists, the watchlist's tickers,
then each ticker and every one of its artifacts with their raw text, so it
made two requests per company and showed no signal. The watchlist summary
answers the whole page in the same few queries however many companies are
watched.
"""

# pylint: disable=redefined-outer-name

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
import main
from app.api.deps import get_current_investor
from app.core.config import settings
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.investor import Investor
from app.models.ticker import Ticker
from app.models.watchlist import Watchlist
from app.models.watchlist_ticker import WatchlistTicker
from app.read_models.watchlist_summary import read_watchlist_summary
from app.schemas.watchlist_summary import WatchedSignal
from app.services import artifact_summary

SUMMARY = {
    "summary": "The company confirmed its half-year result.",
    "about": "The filing reports the half-year result.",
    "changed": "Profit rose.",
    "matters": "The result supports the dividend.",
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
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@contextmanager
def _statements(db: Session) -> Iterator[list[str]]:
    """The SQL statements the session sends inside the block."""
    statements: list[str] = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", record)


def _when(day: int) -> datetime:
    return datetime(2040, 1, day, tzinfo=timezone.utc)


def _investor(db: Session) -> Investor:
    investor = Investor(
        email=f"watchlist-summary-{uuid.uuid4().hex}@example.com",
        username="Watchlist summary test",
    )
    db.add(investor)
    db.commit()
    return investor


def _watchlist(db: Session, investor: Investor, *, created_day: int = 1) -> Watchlist:
    watchlist = Watchlist(
        investor_id=investor.id,
        name=f"Watchlist {created_day}",
        created_at=_when(created_day),
    )
    db.add(watchlist)
    db.commit()
    return watchlist


def _watched(db: Session, watchlist: Watchlist, *, added_day: int = 1) -> Ticker:
    ticker = Ticker(
        symbol=f"W{uuid.uuid4().hex[:8].upper()}",
        company_name="Watchlist Summary Test Limited",
        exchange="ASX",
        sector="Financials",
    )
    db.add(ticker)
    db.flush()
    db.add(
        WatchlistTicker(
            watchlist_id=watchlist.id,
            ticker_id=ticker.id,
            added_at=_when(added_day),
        )
    )
    db.commit()
    return ticker


def _filing(
    db: Session, ticker: Ticker, *, day: int, about: str | None = None, **values
) -> Artifact:
    values.setdefault("published_at", _when(day))
    artifact = Artifact(
        ticker_id=ticker.id,
        source_type="asx_announcement",
        artifact_type="asx_announcement_other",
        title=f"Filing {day}",
        raw_text="Raw filing text that is not a summary.",
        content_hash=f"watchlist-summary-{uuid.uuid4()}",
        **values,
    )
    db.add(artifact)
    db.commit()
    if about:
        summary = artifact_summary.from_answer(
            {**SUMMARY, "about": about}, model="bedrock:test-model", prompt_version="v1"
        )
        artifact_summary.record(db, artifact, summary)
        db.commit()
    return artifact


def _analyse(db: Session, artifact: Artifact, label: str, confidence: float) -> None:
    db.add(
        ArtifactSentiment(
            artifact_id=artifact.id,
            sentiment_label=label,
            confidence_score=confidence,
            model_used="ProsusAI/finbert",
            created_at=_when(20),
        )
    )
    db.commit()


def test_an_investor_without_a_watchlist_sees_no_companies(db_session: Session) -> None:
    summary = read_watchlist_summary(db_session, _investor(db_session).id)

    assert summary.watchlist is None
    assert summary.companies == []


def test_each_company_shows_its_latest_signal_and_brief(db_session: Session) -> None:
    investor = _investor(db_session)
    watchlist = _watchlist(db_session, investor)
    covered = _watched(db_session, watchlist, added_day=1)
    _filing(db_session, covered, day=1, about="An older filing.")
    latest = _filing(db_session, covered, day=3, about="The   filing reports the result.")
    _analyse(db_session, latest, "positive", 0.88)
    bare = _watched(db_session, watchlist, added_day=2)
    undated = _watched(db_session, watchlist, added_day=3)
    _filing(db_session, undated, day=1, published_at=None, created_at=_when(5))

    first, second, third = read_watchlist_summary(db_session, investor.id).companies

    assert (first.ticker_id, first.symbol, first.exchange, first.sector) == (
        covered.id,
        covered.symbol,
        "ASX",
        "Financials",
    )
    assert first.latest_signal == WatchedSignal(
        sentiment_label="positive",
        confidence_score=0.88,
        model_used="ProsusAI/finbert",
        analyzed_at=_when(20),
    )
    assert first.brief == "The filing reports the result."
    assert first.last_brief_at == _when(3)
    assert (second.ticker_id, second.latest_signal, second.brief, second.last_brief_at) == (
        bare.id,
        None,
        None,
        None,
    )
    # An unsummarised record has no brief, and is dated when it was collected.
    assert (third.brief, third.last_brief_at) == (None, _when(5))


def test_another_investors_watchlist_is_not_shown(db_session: Session) -> None:
    owner, other = _investor(db_session), _investor(db_session)
    _watched(db_session, _watchlist(db_session, owner))

    assert read_watchlist_summary(db_session, other.id).watchlist is None
    assert len(read_watchlist_summary(db_session, owner.id).companies) == 1


def test_the_oldest_watchlist_is_the_one_shown(db_session: Session) -> None:
    investor = _investor(db_session)
    _watched(db_session, _watchlist(db_session, investor, created_day=5))
    oldest = _watchlist(db_session, investor, created_day=2)

    summary = read_watchlist_summary(db_session, investor.id)

    assert summary.watchlist.id == oldest.id
    assert summary.companies == []


def test_companies_come_in_the_order_they_were_added(db_session: Session) -> None:
    investor = _investor(db_session)
    watchlist = _watchlist(db_session, investor)
    third = _watched(db_session, watchlist, added_day=3)
    first = _watched(db_session, watchlist, added_day=1)
    second = _watched(db_session, watchlist, added_day=2)

    companies = read_watchlist_summary(db_session, investor.id).companies

    assert [company.ticker_id for company in companies] == [first.id, second.id, third.id]


def test_the_read_runs_the_same_queries_however_many_companies(db_session: Session) -> None:
    counts = []
    for companies in (1, 3):
        investor = _investor(db_session)
        watchlist = _watchlist(db_session, investor)
        for day in range(1, companies + 1):
            ticker = _watched(db_session, watchlist, added_day=day)
            filing = _filing(db_session, ticker, day=day, about="A brief.")
            _analyse(db_session, filing, "neutral", 0.7)
        investor_id = investor.id
        db_session.expire_all()
        with _statements(db_session) as statements:
            assert len(read_watchlist_summary(db_session, investor_id).companies) == companies
        counts.append(len(statements))

    assert counts[0] == counts[1]


def test_the_summary_route_needs_a_signed_in_investor() -> None:
    main.app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        with patch.object(main.settings, "AUTH_PROVIDER", "legacy"):
            response = TestClient(main.app).get("/watchlists/me/summary")
    finally:
        main.app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 401


def test_the_summary_route_answers_the_summary_schema(db_session: Session) -> None:
    investor = _investor(db_session)
    watchlist = _watchlist(db_session, investor)
    ticker = _watched(db_session, watchlist)
    _analyse(db_session, _filing(db_session, ticker, day=2, about="A brief."), "negative", 0.8)
    main.app.dependency_overrides[get_db] = lambda: db_session
    main.app.dependency_overrides[get_current_investor] = lambda: investor
    try:
        response = TestClient(main.app).get("/watchlists/me/summary")
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_investor, None)

    assert response.status_code == 200
    body = response.json()
    assert body["watchlist"]["id"] == str(watchlist.id)
    [company] = body["companies"]
    assert (company["symbol"], company["brief"]) == (ticker.symbol, "A brief.")
    assert company["latest_signal"]["sentiment_label"] == "negative"
