"""Database implementation tests.

This file verifies that the backend database layer is usable from the
application's point of view. It does not only check that SQLAlchemy can create a
single table; it also checks that the real migrated schema and the ORM
relationships used by the API can work together.

The tests run against Postgres using ``settings.DATABASE_URL``, the same database
backend used by Docker and production-like runs. If Postgres is not available they
skip themselves, which keeps local test runs useful while still giving the Docker
test environment a real database verification path.

The schema these tests cover is the current migrated application schema.
"""

import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import Request
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, configure_mappers, sessionmaker
from starlette.responses import Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.core.config import settings
from app.database.base import Base
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.ticker import Ticker
from app.models.watchlist import Watchlist
from app.models.watchlist_ticker import WatchlistTicker

# Every application table. Kept as an exact set so model and migration drift fails.
EXPECTED_TABLES = {
    "artifacts",
    "artifact_sentiments",
    "artifact_summaries",
    "artifact_ticker_mentions",
    "auth_sessions",
    "information_platforms",
    "investors",
    "scrape_runs",
    "tickers",
    "watchlists",
    "watchlist_tickers",
}

# Tables removed by the schema refactor. If one of these comes back it means a stale
# migration ran, or a model was reintroduced without the schema being reconsidered.
DROPPED_TABLES = {
    "alerts",
    "artifact_chunks",
    "artifact_topics",
    "claims",
    "claim_sources",
    "extracted_facts",
    "llm_runs",
    "market_data",
    "reports",
    "report_claims",
    "results",
    "topics",
}


def _database_engine() -> Engine:
    """Create a SQLAlchemy engine for the configured application database.

    The backend reads its database URL from ``settings.DATABASE_URL``. In Docker
    test runs this points at the Postgres service from ``docker-compose-tests``.
    On a developer machine it may point at a local Postgres instance.

    The function performs a minimal ``SELECT 1`` query before returning the
    engine. That tells us whether the database server is reachable and whether
    the configured credentials are valid. If the connection fails, pytest skips
    the integration test instead of failing every local run that does not have
    Postgres running.
    """
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"Database is not available: {exc}")
    return engine


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """Provide a temporary database session for integration tests.

    The fixture opens one connection, starts a transaction, and binds a
    SQLAlchemy ``Session`` to that connection. Tests can freely insert, update,
    commit, and query data through the session.

    After the test finishes, the outer transaction is rolled back. This keeps
    the database clean even though individual tests call ``commit()`` to verify
    real database write behavior. Without this rollback wrapper, test records
    such as generated tickers and artifacts would remain in the shared test
    database after each run.
    """
    engine = _database_engine()
    connection = engine.connect()
    transaction = connection.begin()
    TestingSessionLocal = sessionmaker(bind=connection)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_sqlalchemy_mappers_configure() -> None:
    """Verify that all SQLAlchemy model relationships are valid.

    SQLAlchemy relationships are resolved lazily. A broken relationship can
    exist in model code without failing until an endpoint tries to query it.
    ``configure_mappers()`` forces SQLAlchemy to resolve those relationships
    immediately.

    This catches database implementation mistakes such as:
    - a relationship pointing at a model class that does not exist;
    - ``back_populates`` names that do not match on both sides;
    - joins that cannot be inferred from the declared foreign keys.

    This matters most after a schema change that deletes models: a surviving
    relationship still pointing at a deleted class fails here rather than at
    request time.
    """
    configure_mappers()


def test_migrated_database_matches_the_application_schema() -> None:
    """The migrated database should contain exactly the application tables.

    The application relies on Alembic migrations to create the real Postgres
    schema. This test introspects the connected database and confirms that the
    tables required by the current models exist, and that the tables removed by
    the schema refactor are actually gone.

    It protects against cases where:
    - the database container started but migrations did not run;
    - a migration accidentally omitted a model table;
    - a table was renamed in code but not reflected in the migration;
    - a database predating the refactor was reused instead of recreated.

    ``alembic_version`` is Alembic's own bookkeeping table and is ignored.
    """
    engine = _database_engine()
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    table_names.discard("alembic_version")

    assert table_names == EXPECTED_TABLES
    assert not (table_names & DROPPED_TABLES)


def test_models_and_migration_agree_on_columns() -> None:
    """Every ORM column should exist in the migrated database, and vice versa.

    A model column with no matching database column fails at query time with a
    confusing ``UndefinedColumn`` error from Postgres, usually only on the one
    endpoint that touches it. Comparing the two directly turns that into an
    explicit failure naming the table and column.
    """
    engine = _database_engine()
    try:
        inspector = inspect(engine)
        for table_name in sorted(EXPECTED_TABLES):
            db_columns = {column["name"] for column in inspector.get_columns(table_name)}
            model_columns = {
                column.name for column in Base.metadata.tables[table_name].columns
            }
            assert model_columns == db_columns, (
                f"{table_name}: model columns {sorted(model_columns)} "
                f"!= database columns {sorted(db_columns)}"
            )
    finally:
        engine.dispose()


def test_password_hashing_verifies_and_rejects_wrong_password() -> None:
    """Password hashes should verify only the original password."""
    from app.core.security import hash_password, verify_password

    password_hash = hash_password("correct-password")

    assert verify_password("correct-password", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_auth_schema_rejects_invalid_email() -> None:
    """Auth schemas should require a real email address."""
    from pydantic import ValidationError

    from app.schemas.auth import SignUpRequest

    with pytest.raises(ValidationError):
        SignUpRequest(name="Jane Doe", email="not-an-email", password="password123")


def test_sign_up_sets_session_cookie_and_me_loads_investor(db_session: Session) -> None:
    """Signing up creates a DB session and exposes it through an httpOnly cookie."""
    from app.api.deps import get_current_investor
    from app.api.routes.auth import sign_up
    from app.models.auth_session import AuthSession
    from app.schemas.auth import SignUpRequest

    unique_email = f"auth-{uuid.uuid4().hex}@example.com"
    response = Response()

    result = sign_up(
        body=SignUpRequest(
            name="Auth Test",
            email=unique_email,
            password="password123",
        ),
        response=response,
        db=db_session,
    )

    cookie = SimpleCookie(response.headers["set-cookie"])
    session_cookie = cookie[settings.SESSION_COOKIE_NAME]

    assert session_cookie["httponly"]
    assert result["investor"].email == unique_email
    assert (
        db_session.query(AuthSession)
        .filter(AuthSession.investor_id == result["investor"].id)
        .count()
        == 1
    )

    current_investor = get_current_investor(
        session_token=session_cookie.value,
        db=db_session,
    )

    assert current_investor.email == unique_email


def test_sign_out_deletes_session(db_session: Session) -> None:
    """Signing out removes the matching DB session."""
    from app.api.routes.auth import sign_out, sign_up
    from app.models.auth_session import AuthSession
    from app.schemas.auth import SignUpRequest

    response = Response()
    result = sign_up(
        body=SignUpRequest(
            name="Sign Out Test",
            email=f"signout-{uuid.uuid4().hex}@example.com",
            password="password123",
        ),
        response=response,
        db=db_session,
    )
    cookie = SimpleCookie(response.headers["set-cookie"])
    session_token = cookie[settings.SESSION_COOKIE_NAME].value

    request = Request(
        {
            "type": "http",
            "headers": [
                (
                    b"cookie",
                    f"{settings.SESSION_COOKIE_NAME}={session_token}".encode("utf-8"),
                )
            ],
        }
    )
    sign_out(request=request, response=Response(), db=db_session)

    assert (
        db_session.query(AuthSession)
        .filter(AuthSession.investor_id == result["investor"].id)
        .count()
        == 0
    )


def test_sign_in_accepts_valid_credentials_and_rejects_invalid_password(
    db_session: Session,
) -> None:
    """Signing in should validate stored password hashes."""
    from fastapi import HTTPException

    from app.api.routes.auth import sign_in, sign_up
    from app.models.auth_session import AuthSession
    from app.schemas.auth import SignInRequest, SignUpRequest

    email = f"signin-{uuid.uuid4().hex}@example.com"
    sign_up(
        body=SignUpRequest(
            name="Sign In Test",
            email=email,
            password="password123",
        ),
        response=Response(),
        db=db_session,
    )

    with pytest.raises(HTTPException) as exc_info:
        sign_in(
            body=SignInRequest.model_validate(
                {"email": email, "password": "wrong-password"}
            ),
            response=Response(),
            db=db_session,
        )

    assert exc_info.value.status_code == 401

    response = Response()
    result = sign_in(
        body=SignInRequest(email=email, password="password123"),
        response=response,
        db=db_session,
    )
    cookie = SimpleCookie(response.headers["set-cookie"])
    session_token = cookie[settings.SESSION_COOKIE_NAME].value

    assert result["investor"].email == email
    assert (
        db_session.query(AuthSession)
        .filter(AuthSession.token_hash.isnot(None))
        .count()
        >= 1
    )
    assert session_token


def test_auth_me_rejects_missing_session_cookie(db_session: Session) -> None:
    """The auth identity dependency should reject requests without a session."""
    from fastapi import HTTPException

    from app.api.deps import get_current_investor

    with pytest.raises(HTTPException) as exc_info:
        get_current_investor(session_token=None, db=db_session)

    assert exc_info.value.status_code == 401


def test_watchlist_contract_keeps_investor_id_and_old_crud_signature(
    db_session: Session,
) -> None:
    """The shared watchlist contract should remain backward-compatible."""
    from app.crud import investor as investor_crud
    from app.crud import watchlist as watchlist_crud
    from app.schemas.investor import InvestorCreate
    from app.schemas.watchlist import WatchlistCreate

    investor = investor_crud.create_investor(
        db_session,
        InvestorCreate(
            email=f"contract-{uuid.uuid4().hex}@example.com",
            username="Contract Test",
        ),
    )

    watchlist = watchlist_crud.create_watchlist(
        db_session,
        WatchlistCreate(investor_id=investor.id, name="MVP Watchlist"),
    )

    assert watchlist.investor_id == investor.id


def test_watchlist_tickers_link_investors_to_tickers(db_session: Session) -> None:
    """Verify the watchlist join table can be written and read back.

    ``watchlist_tickers`` uses a composite primary key of (watchlist_id,
    ticker_id) rather than a surrogate id. This is the shape the watchlist page
    depends on when it lists a member's saved companies.
    """
    from app.crud import investor as investor_crud
    from app.schemas.investor import InvestorCreate

    investor = investor_crud.create_investor(
        db_session,
        InvestorCreate(
            email=f"watch-{uuid.uuid4().hex}@example.com",
            username="Watchlist Test",
        ),
    )
    ticker = Ticker(
        symbol=f"W{uuid.uuid4().hex[:8].upper()}",
        company_name="Watchlist Test Limited",
        exchange="ASX",
    )
    watchlist = Watchlist(investor_id=investor.id, name="Join Table Watchlist")
    db_session.add_all([ticker, watchlist])
    db_session.flush()

    db_session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker_id=ticker.id))
    db_session.commit()

    saved = db_session.execute(
        select(WatchlistTicker).where(WatchlistTicker.watchlist_id == watchlist.id)
    ).scalar_one()

    assert saved.ticker_id == ticker.id
    assert saved.added_at is not None


def test_database_can_persist_reddit_artifact(db_session: Session) -> None:
    """Verify a Reddit post artifact can be written and read back.

    Mirrors how POST /reddit/scrape stores posts: an Artifact with
    artifact_type='reddit_post', a content_hash, and artifact_metadata JSONB.
    """
    from app.models.information_platform import InformationPlatform

    platform = InformationPlatform(
        name="Reddit-Test",
        platform_type="social",
        base_url="https://reddit.com",
        scrape_enabled=True,
    )
    db_session.add(platform)
    db_session.flush()

    artifact = Artifact(
        platform_id=platform.id,
        artifact_type="reddit_post",
        title="Test ASX post",
        url="https://reddit.com/r/ASX/comments/test",
        author="testuser",
        raw_text="Some post body",
        published_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        content_hash=f"reddit-test-{uuid.uuid4()}",
        artifact_metadata={
            "reddit_id": "test123",
            "score": 42,
            "upvote_ratio": 0.95,
            "num_comments": 5,
            "flair": "Discussion",
            "is_self": True,
            "external_url": None,
            "subreddit": "ASX",
        },
    )
    db_session.add(artifact)
    db_session.commit()

    saved = db_session.execute(
        select(Artifact).where(Artifact.id == artifact.id)
    ).scalar_one()

    assert saved.artifact_type == "reddit_post"
    assert saved.author == "testuser"
    assert saved.artifact_metadata["score"] == 42
    assert saved.artifact_metadata["subreddit"] == "ASX"


def test_ticker_mentions_connect_social_sentiment_to_ticker(
    db_session: Session,
) -> None:
    """A social artifact can reach ticker sentiment through the join table."""
    from app.api.routes.category_sentiment import read_ticker_category_sentiment

    ticker = Ticker(
        symbol=f"P{uuid.uuid4().hex[:8].upper()}",
        company_name="Public Discussion Test Limited",
        exchange="ASX",
    )
    db_session.add(ticker)
    db_session.flush()

    artifact = Artifact(
        ticker_id=None,
        source_type="mastodon",
        artifact_type="mastodon_post",
        title=f"Investors discuss {ticker.symbol}",
        url="https://aus.social/@investor/123",
        raw_text=f"I am positive about {ticker.symbol} after the update.",
        content_hash=f"public-discussion-{uuid.uuid4()}",
        published_at=datetime.now(timezone.utc),
    )
    db_session.add(artifact)
    db_session.flush()
    db_session.add_all(
        [
            ArtifactTickerMention(
                artifact_id=artifact.id,
                ticker_id=ticker.id,
                match_method="ticker_symbol",
                match_confidence=0.95,
                matched_text=ticker.symbol,
            ),
            ArtifactSentiment(
                artifact_id=artifact.id,
                sentiment_label="positive",
                confidence_score=0.9,
                model_used="test-finbert",
            ),
        ]
    )
    db_session.commit()

    result = read_ticker_category_sentiment(ticker.symbol, db_session)
    discussion = result["categories"]["user_discussion"]

    assert artifact.ticker_id is None
    assert discussion["available"] is True
    assert discussion["sentiment_label"] == "positive"
    assert discussion["sources_count"] == 1
    assert discussion["sources"] == [
        {
            "source_type": "mastodon",
            "title": f"Investors discuss {ticker.symbol}",
            "url": "https://aus.social/@investor/123",
            "author": None,
            "published_at": artifact.published_at,
        }
    ]


def test_public_discussion_backfill_is_dry_run_first_and_idempotent(
    db_session: Session,
) -> None:
    from app.services.public_discussion import backfill_artifact_ticker_mentions

    symbol = f"Q{uuid.uuid4().hex[:5].upper()}"
    ticker = Ticker(
        symbol=symbol,
        company_name="Quartz Exchange Limited",
        exchange="ASX",
    )
    db_session.add(ticker)
    db_session.flush()
    matching = Artifact(
        source_type="reddit",
        artifact_type="reddit_post",
        title=f"Watching ${symbol} today",
        raw_text="The update is worth reading.",
        url="https://reddit.test/matching",
        content_hash=f"backfill-match-{uuid.uuid4()}",
        published_at=datetime.now(timezone.utc),
    )
    unrelated = Artifact(
        source_type="mastodon",
        artifact_type="mastodon_post",
        title=f"prefix{symbol}suffix is a username",
        raw_text="No company discussion here.",
        url="https://aus.social/unrelated",
        content_hash=f"backfill-unrelated-{uuid.uuid4()}",
        published_at=datetime.now(timezone.utc),
    )
    db_session.add_all([matching, unrelated])
    db_session.commit()

    dry_run = backfill_artifact_ticker_mentions(db_session, execute=False)

    assert dry_run == {
        "dry_run": True,
        "artifacts_scanned": 2,
        "matched_artifacts": 1,
        "matches_found": 1,
        "new_mentions": 1,
        "mentions_written": 0,
    }
    assert db_session.query(ArtifactTickerMention).count() == 0

    executed = backfill_artifact_ticker_mentions(db_session, execute=True)
    repeated = backfill_artifact_ticker_mentions(db_session, execute=True)

    assert executed["mentions_written"] == 1
    assert repeated["new_mentions"] == 0
    assert repeated["mentions_written"] == 0
    mention = db_session.query(ArtifactTickerMention).one()
    assert mention.artifact_id == matching.id
    assert mention.ticker_id == ticker.id
    assert mention.match_method == "cashtag"


def test_artifact_carries_its_sentiment_and_summary(db_session: Session) -> None:
    """Verify the artifact analysis chain can be written and read back.

    ``Ticker -> Artifact -> ArtifactSentiment / ArtifactSummary`` is the whole
    analysis path that survived the schema refactor. ``parsing/storage.py``
    writes all three in one pass, and the ticker overview and deep-dive
    endpoints read them back through the ``sentiments`` and ``summaries``
    backrefs, so both directions need to work.
    """
    ticker = Ticker(
        symbol=f"S{uuid.uuid4().hex[:8].upper()}",
        company_name="Sentiment Test Limited",
        exchange="ASX",
    )
    db_session.add(ticker)
    db_session.flush()

    artifact = Artifact(
        ticker_id=ticker.id,
        source_type="asx_announcement",
        artifact_type="dividend_announcement",
        title="Dividend timetable update",
        raw_text="The company confirmed its dividend payment date.",
        content_hash=f"analysis-{uuid.uuid4()}",
        published_at=datetime(2040, 1, 2, 10, 0, tzinfo=timezone.utc),
    )
    db_session.add(artifact)
    db_session.flush()

    db_session.add_all([
        ArtifactSentiment(
            artifact_id=artifact.id,
            sentiment_label="positive",
            stance="positive",
            confidence_score=0.87,
            model_used="test-finbert",
        ),
        ArtifactSummary(
            artifact_id=artifact.id,
            summary_text="The dividend payment date was confirmed.",
            model_used="test-groq",
        ),
    ])
    db_session.commit()

    saved = db_session.execute(
        select(Artifact).where(Artifact.id == artifact.id)
    ).scalar_one()

    assert saved.ticker.symbol == ticker.symbol
    assert saved.sentiments[0].sentiment_label == "positive"
    assert float(saved.sentiments[0].confidence_score) == pytest.approx(0.87)
    assert saved.summaries[0].summary_text == (
        "The dividend payment date was confirmed."
    )


def test_announcements_feed_and_trending_only_count_asx_artifacts(
    db_session: Session,
) -> None:
    """Announcement APIs should count only ASX-sourced artifacts.

    Duplicates are no longer filtered at read time: ``parsing/storage.py`` skips
    them at insert time by ``content_hash``, so an announcement never reaches the
    table twice.
    """
    from datetime import date

    from app.api.routes.announcement import (
        list_announcements,
        list_trending_announcements,
    )

    symbol = f"A{uuid.uuid4().hex[:8].upper()}"
    ticker = Ticker(
        symbol=symbol,
        company_name="Announcement API Test Limited",
        exchange="ASX",
        sector="Materials",
    )
    db_session.add(ticker)
    db_session.flush()

    published_at = datetime(2040, 1, 2, 10, 0, tzinfo=timezone.utc)
    announcement = Artifact(
        ticker_id=ticker.id,
        source_type="asx_announcement",
        artifact_type="dividend_announcement",
        title="Visible dividend update",
        raw_text="Dividend announcement body",
        published_at=published_at,
        content_hash=f"visible-{uuid.uuid4()}",
    )
    reddit = Artifact(
        ticker_id=ticker.id,
        source_type="reddit",
        artifact_type="reddit_post",
        title="Non ASX source",
        raw_text="Reddit post body",
        published_at=published_at,
        content_hash=f"reddit-{uuid.uuid4()}",
    )
    db_session.add_all([announcement, reddit])
    db_session.commit()

    announcements = list_announcements(
        start_date=date(2040, 1, 1),
        end_date=date(2040, 1, 3),
        db=db_session,
    )
    announcement_ids = {item.id for item in announcements}

    assert announcement.id in announcement_ids
    assert reddit.id not in announcement_ids

    trending = list_trending_announcements(days=1, limit=10, db=db_session)
    trend = next(item for item in trending if item.symbol == symbol)

    assert trend.count == 1


def test_ticker_brief_aside_returns_empty_database_state(
    db_session: Session,
) -> None:
    """The ticker sidebar API should not fall back to mocked values."""
    from app.api.routes import ticker as ticker_route

    symbol = f"E{uuid.uuid4().hex[:8].upper()}"
    ticker = Ticker(
        symbol=symbol,
        company_name="Empty Sidebar Test Limited",
        exchange="ASX",
    )
    db_session.add(ticker)
    db_session.commit()

    with patch.object(ticker_route, "_live_quote", return_value=None):
        result = ticker_route.get_ticker_brief_aside(symbol.lower(), db=db_session)

    assert result["key_numbers"] == [
        {"label": "Current price", "value": "N/A"},
        {"label": "Day change", "value": "N/A"},
        {"label": "Latest filing", "value": "No filings yet"},
        {"label": "Latest type", "value": "No filings yet"},
    ]
    assert result["themes"] == []


def test_ticker_overview_reports_live_quote(db_session: Session) -> None:
    """The overview API should format the live quote it is given.

    The quote is fetched from Yahoo at request time rather than stored, so the
    lookup is patched here and only the formatting and failure handling are
    under test.
    """
    from app.api.routes import ticker as ticker_route

    symbol = f"Q{uuid.uuid4().hex[:8].upper()}"
    ticker = Ticker(
        symbol=symbol,
        company_name="Quote Test Limited",
        exchange="ASX",
    )
    db_session.add(ticker)
    db_session.commit()

    with patch.object(ticker_route, "_live_quote", return_value=(31.25, 30.0)):
        result = ticker_route.get_ticker_overview(symbol.lower(), db=db_session)

    assert result["current_price"] == "$31.25"
    assert result["day_change"] == "+4.17%"

    with patch.object(ticker_route, "_live_quote", return_value=None):
        unavailable = ticker_route.get_ticker_overview(symbol.lower(), db=db_session)

    assert unavailable["current_price"] == "N/A"
    assert unavailable["day_change"] == "N/A"


def test_scrape_pipeline_state_is_idempotent(db_session: Session) -> None:
    """Duplicate queue work updates one artifact and one pair of results."""
    from app.crud import artifact as artifact_crud
    from app.crud import scrape_run as scrape_run_crud
    from app.models.artifact_sentiment import ArtifactSentiment
    from app.models.artifact_summary import ArtifactSummary

    request_key = f"test:{uuid.uuid4()}"
    run, created = scrape_run_crud.get_or_create_queued_run(
        db_session,
        ticker="CSL",
        source_url="https://investors.csl.com/investors/asx-announcements",
        idempotency_key=request_key,
    )
    duplicate_run, duplicate_created = scrape_run_crud.get_or_create_queued_run(
        db_session,
        ticker="CSL",
        source_url="https://investors.csl.com/investors/asx-announcements",
        idempotency_key=request_key,
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate_run.id == run.id
    assert run.status == "enqueueing"

    scrape_run_crud.mark_run_queued_if_enqueueing(db_session, run.id)
    scrape_run_crud.mark_run_discovery_started(db_session, run.id)
    scrape_run_crud.mark_run_queued_if_enqueueing(db_session, run.id)
    db_session.refresh(run)
    assert run.status == "discovering"

    canonical_url = f"https://example.test/{uuid.uuid4()}.pdf"
    artifact, artifact_created = scrape_run_crud.get_or_create_artifact(
        db_session,
        scrape_run_id=run.id,
        canonical_url=canonical_url,
        document_url=canonical_url,
        source_adapter="csl",
        source_id="csl-test-document",
        title="CSL test announcement",
    )
    duplicate_artifact, duplicate_artifact_created = (
        scrape_run_crud.get_or_create_artifact(
            db_session,
            scrape_run_id=run.id,
            canonical_url=canonical_url,
            document_url=canonical_url,
            source_adapter="csl",
            source_id="csl-test-document",
        )
    )
    assert artifact_created is True
    assert duplicate_artifact_created is False
    assert duplicate_artifact.id == artifact.id

    second_run, _ = scrape_run_crud.get_or_create_queued_run(
        db_session,
        ticker="CSL",
        source_url="https://investors.csl.com/investors/asx-announcements",
        idempotency_key=f"test:{uuid.uuid4()}",
    )
    prior_artifact, prior_artifact_created = scrape_run_crud.get_or_create_artifact(
        db_session,
        scrape_run_id=second_run.id,
        canonical_url=canonical_url,
        document_url=canonical_url,
        source_adapter="csl",
        source_id="csl-test-document",
    )
    assert prior_artifact_created is False
    assert prior_artifact.id == artifact.id
    assert prior_artifact.scrape_run_id == run.id

    scrape_run_crud.mark_artifact_download_started(db_session, artifact.id)
    scrape_run_crud.mark_artifact_stored(
        db_session,
        artifact.id,
        checksum_sha256="a" * 64,
        s3_bucket="raw-documents",
        s3_key=f"raw/CSL/{artifact.id}/{'a' * 64}.pdf",
        content_type="application/pdf",
        file_size_bytes=128,
    )
    scrape_run_crud.mark_artifact_analysis_started(db_session, artifact.id)

    analysis = {
        "raw_text": "CSL announced a test result.",
        "metadata": {"page_count": 1},
        "summary": {
            "summary_text": "CSL announced a test result.",
            "model_used": "test-summary",
        },
        "sentiment": {
            "sentiment_label": "neutral",
            "confidence_score": 0.9,
            "model_used": "test-finbert",
        },
    }
    artifact_crud.store_artifact_analysis(
        db_session,
        artifact_id=artifact.id,
        **analysis,
    )
    artifact_crud.store_artifact_analysis(
        db_session,
        artifact_id=artifact.id,
        **analysis,
    )
    scrape_run_crud.mark_artifact_analysis_completed(db_session, artifact.id)
    scrape_run_crud.mark_artifact_analysis_completed(db_session, artifact.id)
    scrape_run_crud.mark_run_discovery_completed(
        db_session,
        run.id,
        items_found=1,
    )

    db_session.refresh(run)
    db_session.refresh(artifact)
    assert run.status == "completed"
    assert run.items_downloaded == 1
    assert run.items_analyzed == 1
    assert artifact.download_status == "stored"
    assert artifact.analysis_status == "completed"
    assert (
        db_session.query(ArtifactSummary)
        .filter(ArtifactSummary.artifact_id == artifact.id)
        .count()
        == 1
    )

    scrape_run_crud.mark_run_discovery_started(db_session, run.id)
    scrape_run_crud.mark_run_discovery_completed(db_session, run.id, items_found=1)
    scrape_run_crud.mark_run_discovery_failed(
        db_session,
        run.id,
        error="late duplicate failed",
    )
    scrape_run_crud.mark_artifact_download_failed(
        db_session,
        artifact.id,
        error="late duplicate download failed",
    )
    scrape_run_crud.mark_artifact_analysis_failed(
        db_session,
        artifact.id,
        error="late duplicate analysis failed",
    )
    db_session.refresh(run)
    db_session.refresh(artifact)
    assert run.status == "completed"
    assert run.items_failed == 0
    assert artifact.download_status == "stored"
    assert artifact.analysis_status == "completed"
    assert (
        db_session.query(ArtifactSentiment)
        .filter(ArtifactSentiment.artifact_id == artifact.id)
        .count()
        == 1
    )
