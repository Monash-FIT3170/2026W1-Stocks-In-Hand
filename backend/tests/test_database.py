"""Database implementation tests.

This file verifies that the backend database layer is usable from the
application's point of view. It does not only check that SQLAlchemy can create a
single table; it also checks that the real migrated schema and the ORM
relationships used by the API can work together.

The tests are split into two groups:
- Postgres integration checks that use ``settings.DATABASE_URL``. These tests
  validate the same database backend used by Docker and production-like runs.
- A lightweight SQLite smoke test for the legacy ``Result`` table. That table
  is independent from the main stock/report schema, so it can be tested without
  requiring Postgres.

If Postgres is not available, the Postgres-specific tests skip themselves. This
keeps local test runs useful while still giving the Docker test environment a
real database verification path.
"""

import sys
import uuid
from http.cookies import SimpleCookie
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from starlette.responses import Response
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, configure_mappers, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.core.config import settings
from app.database.base import Base
from app.models.artifact import Artifact
from app.models.claim import Claim
from app.models.claim_source import ClaimSource
from app.models.report import Report
from app.models.report_claim import ReportClaim
from app.models.result import Result
from app.models.ticker import Ticker


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
    such as generated tickers and reports would remain in the shared test
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

    This is especially important for the report database flow, because
    ``crud/report.py`` expects to navigate from reports to report claims, then
    claims, claim sources, and source artifacts.
    """
    configure_mappers()


def test_migrated_database_has_expected_tables() -> None:
    """Verify that the migrated database contains the backend's core tables.

    The application relies on Alembic migrations to create the real Postgres
    schema. This test introspects the connected database and confirms that the
    tables required by the current models exist.

    It protects against cases where:
    - the database container started but migrations did not run;
    - a migration accidentally omitted a model table;
    - a table was renamed in code but not reflected in the migration.

    The assertion checks for a required subset instead of exact equality so the
    database can contain Alembic's own version table or other harmless support
    tables.
    """
    engine = _database_engine()
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    expected_tables = {
        "alerts",
        "artifacts",
        "artifact_chunks",
        "artifact_sentiments",
        "artifact_summaries",
        "artifact_topics",
        "auth_sessions",
        "claim_sources",
        "claims",
        "extracted_facts",
        "information_platforms",
        "investors",
        "llm_runs",
        "market_data",
        "reports",
        "report_claims",
        "results",
        "scrape_runs",
        "tickers",
        "topics",
        "watchlists",
        "watchlist_tickers",
    }

    assert expected_tables.issubset(table_names)


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
    from app.core.config import settings
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
    from app.core.config import settings
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
    from app.core.config import settings
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


def test_watchlist_and_alert_contracts_keep_investor_id_and_old_crud_signature(
    db_session: Session,
) -> None:
    """Shared watchlist/alert contracts should remain backward-compatible."""
    from app.crud import alert as alert_crud
    from app.crud import investor as investor_crud
    from app.crud import watchlist as watchlist_crud
    from app.schemas.alert import AlertCreate
    from app.schemas.investor import InvestorCreate
    from app.schemas.watchlist import WatchlistCreate

    investor = investor_crud.create_investor(
        db_session,
        InvestorCreate(
            email=f"contract-{uuid.uuid4().hex}@example.com",
            username="Contract Test",
        ),
    )

    ticker = Ticker(
        symbol=f"C{uuid.uuid4().hex[:8].upper()}",
        company_name="Contract Test Limited",
        exchange="ASX",
    )
    db_session.add(ticker)
    db_session.flush()

    watchlist_payload = WatchlistCreate(investor_id=investor.id, name="MVP Watchlist")
    alert_payload = AlertCreate(
        investor_id=investor.id,
        ticker_id=ticker.id,
        alert_type="price",
        title="Contract alert",
        message="Still accepts investor_id",
    )

    watchlist = watchlist_crud.create_watchlist(db_session, watchlist_payload)
    alert = alert_crud.create_alert(db_session, alert_payload)

    assert watchlist.investor_id == investor.id
    assert alert.investor_id == investor.id


def test_database_can_persist_report_claim_relationships(
    db_session: Session,
) -> None:
    """Verify the main report evidence relationship can be written and read.

    This is the most important database integration test for the report system.
    It creates a small, realistic chain of related records:

    ``Ticker -> Report -> ReportClaim -> Claim -> ClaimSource -> Artifact``

    That chain mirrors how the API expects report data to work:
    - a ticker identifies the listed company;
    - a report belongs to a ticker;
    - a claim belongs to the same ticker;
    - ``report_claims`` links the report to the claim;
    - ``claim_sources`` links the claim to the source artifact that supports it.

    After committing the records, the test loads the report again and navigates
    through the ORM relationships. This verifies both sides of the database
    implementation: the foreign keys can store valid data, and the SQLAlchemy
    relationships can read that data back in the shape used by the API.
    """
    unique_suffix = uuid.uuid4().hex[:8].upper()
    ticker = Ticker(
        symbol=f"T{unique_suffix}",
        company_name="Database Test Limited",
        exchange="ASX",
    )
    db_session.add(ticker)
    db_session.flush()

    report = Report(
        ticker_id=ticker.id,
        report_title="Database Test Report",
        report_text="A generated report body.",
        report_type="daily",
        model_used="test-model",
    )
    claim = Claim(
        ticker_id=ticker.id,
        claim_text="The company reported stronger revenue.",
        claim_type="financial",
        reliability_label="high",
        generated_by_model="test-model",
    )
    artifact = Artifact(
        ticker_id=ticker.id,
        artifact_type="news",
        title="Revenue update",
        raw_text="The company reported stronger revenue.",
        content_hash=f"test-{uuid.uuid4()}",
    )
    db_session.add_all([report, claim, artifact])
    db_session.flush()

    report_claim = ReportClaim(
        report_id=report.id,
        claim_id=claim.id,
        display_order=1,
    )
    claim_source = ClaimSource(
        claim_id=claim.id,
        artifact_id=artifact.id,
        evidence_text="The company reported stronger revenue.",
        url="https://example.test/revenue-update",
    )
    db_session.add_all([report_claim, claim_source])
    db_session.commit()

    saved_report = db_session.execute(
        select(Report).where(Report.id == report.id)
    ).scalar_one()

    assert saved_report.report_claims[0].display_order == 1
    assert saved_report.report_claims[0].claim.claim_text == claim.claim_text
    assert saved_report.report_claims[0].claim.claim_sources[0].artifact.title == (
        "Revenue update"
    )


def test_database_can_create_table_insert_and_read_result(tmp_path: Path) -> None:
    """Verify the standalone sentiment ``Result`` table can store data.

    ``Result`` is separate from the stock/report schema. It is used by the
    simple sentiment analysis endpoints in ``main.py`` and does not depend on
    Postgres-specific UUID or JSONB columns.

    This test intentionally uses a temporary SQLite database because it is a
    fast smoke test for basic SQLAlchemy behavior:
    - create the ``results`` table;
    - insert one sentiment result;
    - read it back with a query;
    - confirm the stored values match what was inserted.

    The broader schema is covered by the Postgres tests above. This one remains
    narrow so it can run quickly in environments without a database server.
    """
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(database_url)
    TestingSessionLocal = sessionmaker(bind=engine)

    Base.metadata.create_all(bind=engine, tables=[Result.__table__])

    with TestingSessionLocal() as session:
        result = Result(text="ASX headline", label="positive", score=0.95)
        session.add(result)
        session.commit()

    with TestingSessionLocal() as session:
        saved_result = session.execute(
            select(Result).where(Result.text == "ASX headline")
        ).scalar_one()

    assert saved_result.label == "positive"
    assert saved_result.score == 0.95

def test_database_can_persist_reddit_artifact(db_session: Session) -> None:
    """Verify a Reddit post artifact can be written and read back.

    Mirrors how POST /reddit/scrape stores posts: an Artifact with
    artifact_type='reddit_post', a content_hash, and artifact_metadata JSONB.
    """
    from app.models.information_platform import InformationPlatform
    from datetime import datetime, timezone

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
