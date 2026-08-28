"""Focused contracts for the Phase 3 alert CRUD modules.

The pure tests cover validation and generated PostgreSQL statements without a
database.  Integration tests use the configured Postgres database when it is
available, and otherwise skip cleanly for local runs without Docker.
"""

# pylint: disable=redefined-outer-name,too-few-public-methods,too-many-locals,wrong-import-position

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, object_session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.crud import alert_delivery as delivery_crud
from app.crud import alert_rule as rule_crud
from app.crud import alert_subscription as subscription_crud
from app.crud import watchlist_ticker as watchlist_ticker_crud
from app.models.alert_delivery import AlertDelivery
from app.models.alert_rule import AlertRule
from app.models.alert_subscription import AlertSubscription
from app.models.artifact import Artifact
from app.models.information_platform import InformationPlatform
from app.models.investor import Investor
from app.models.scrape_run import ScrapeRun
from app.models.ticker import Ticker
from app.models.watchlist import Watchlist
from app.models.watchlist_ticker import WatchlistTicker


class _CapturedResult:
    """Return no row while retaining a SQL statement for pure contract tests."""

    def scalar_one_or_none(self) -> None:
        """Represent a statement that did not acquire a claim."""
        return None


class _CapturedSession:
    """Small Session double that records one statement without opening a DB."""

    def __init__(self, artifact_scrape_run_id: uuid.UUID | None = None) -> None:
        self.statement: Any | None = None
        self.commit_count = 0
        self.flush_count = 0
        self.artifact_scrape_run_id = artifact_scrape_run_id

    def execute(self, statement: Any) -> _CapturedResult:
        """Capture the generated statement for later compilation."""
        self.statement = statement
        return _CapturedResult()

    def commit(self) -> None:
        """Match the claim helper's commit boundary without a database."""
        self.commit_count += 1

    def flush(self) -> None:
        """Record a caller-owned write without committing its transaction."""
        self.flush_count += 1

    def scalar(self, statement: Any) -> uuid.UUID | None:
        """Return the configured provenance result for a claim lookup."""
        self.statement = statement
        return self.artifact_scrape_run_id


class _WriteSession:
    """In-memory Session double for checking a mutation's commit policy."""

    def __init__(self, result: AlertRule | AlertSubscription) -> None:
        self.result = result
        self.commit_count = 0
        self.flush_count = 0

    def execute(self, _statement: Any) -> _WriteSession:
        """Return this object as the scalar-returning execution result."""
        return self

    def scalar_one(self) -> uuid.UUID:
        """Return the saved model primary key expected by upsert helpers."""
        return self.result.id

    def get(self, _model: Any, _record_id: uuid.UUID) -> AlertRule | AlertSubscription:
        """Return the prebuilt saved model without a real database round trip."""
        return self.result

    def refresh(self, _model: Any) -> None:
        """Models are already complete in this focused transaction test."""

    def commit(self) -> None:
        """Record an unexpected transaction boundary."""
        self.commit_count += 1

    def flush(self) -> None:
        """Record the expected caller-owned write flush."""
        self.flush_count += 1


def _database_engine() -> Engine:
    """Connect to the configured Postgres database, or skip local integration."""
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
    """Run each integration test inside a rolled-back outer transaction."""
    engine = _database_engine()
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


def _records(db: Session) -> tuple[Investor, Ticker, ScrapeRun, Artifact]:
    """Create an isolated investor, ticker, scrape run, and artifact."""
    suffix = uuid.uuid4().hex
    investor = Investor(email=f"alerts-{suffix}@example.com", username="Alert test")
    ticker = Ticker(
        symbol=f"T{suffix[:8].upper()}",
        company_name="Alert CRUD Test Limited",
        exchange="ASX",
    )
    platform = InformationPlatform(name=f"Alert CRUD {suffix}", platform_type="test")
    db.add_all([investor, ticker, platform])
    db.flush()

    scrape_run = ScrapeRun(platform_id=platform.id, status="completed")
    db.add(scrape_run)
    db.flush()

    artifact = Artifact(
        scrape_run_id=scrape_run.id,
        ticker_id=ticker.id,
        artifact_type="announcement",
        content_hash=f"alert-{suffix}",
    )
    db.add(artifact)
    db.flush()
    return investor, ticker, scrape_run, artifact


def _artifact_for_run(db: Session, ticker_id: uuid.UUID, run_id: uuid.UUID) -> Artifact:
    """Create another unique artifact for a claim outcome test."""
    artifact = Artifact(
        scrape_run_id=run_id,
        ticker_id=ticker_id,
        artifact_type="announcement",
        content_hash=f"alert-{uuid.uuid4().hex}",
    )
    db.add(artifact)
    db.flush()
    return artifact


def test_alert_crud_validation_needs_no_database() -> None:
    """Reject malformed values before CRUD code executes any SQL."""
    db = Mock()
    investor_id = uuid.uuid4()

    with pytest.raises(ValueError, match="valid email"):
        subscription_crud.upsert_subscription(
            db,
            investor_id=investor_id,
            email="not-an-email",
        )
    with pytest.raises(ValueError, match="64 lowercase hex"):
        subscription_crud.get_subscription_by_unsubscribe_token_hash(db, "bad")
    with pytest.raises(ValueError, match="verification status"):
        subscription_crud.update_verification_state(
            db,
            investor_id=investor_id,
            verification_status="unknown",
            expected_email="alerts@example.com",
            expected_verification_requested_at=None,
            expected_verification_status="unverified",
        )
    # Calling without the mandatory guards is the contract under test.
    # pylint: disable=missing-kwoa
    with pytest.raises(TypeError, match="expected_verification_status"):
        subscription_crud.update_verification_state(
            db,
            investor_id=investor_id,
            verification_status="pending",
            expected_email="alerts@example.com",
            expected_verification_requested_at=None,
        )
    with pytest.raises(ValueError, match="enabled"):
        subscription_crud.upsert_subscription(
            db,
            investor_id=investor_id,
            email="alerts@example.com",
            enabled="true",
        )
    with pytest.raises(ValueError, match="between 0 and 1"):
        rule_crud.upsert_default_alert_rule(
            db,
            investor_id=investor_id,
            sentiment_labels=["negative"],
            min_confidence=1.01,
            enabled=True,
        )
    with pytest.raises(ValueError, match="labels must be strings"):
        rule_crud.upsert_default_alert_rule(
            db,
            investor_id=investor_id,
            sentiment_labels=["negative", 1],
            min_confidence=0.75,
            enabled=True,
        )
    with pytest.raises(ValueError, match="sentiment label"):
        rule_crud.upsert_default_alert_rule(
            db,
            investor_id=investor_id,
            sentiment_labels=["unknown"],
            min_confidence=0.75,
            enabled=True,
        )
    with pytest.raises(ValueError, match="rule type"):
        rule_crud.upsert_default_alert_rule(
            db,
            investor_id=investor_id,
            sentiment_labels=["negative"],
            min_confidence=0.75,
            enabled=True,
            rule_type=True,
        )
    with pytest.raises(ValueError, match="enabled"):
        rule_crud.upsert_default_alert_rule(
            db,
            investor_id=investor_id,
            sentiment_labels=["negative"],
            min_confidence=0.75,
            enabled="false",
        )
    with pytest.raises(ValueError, match="stale_after_minutes"):
        delivery_crud.claim(
            db,
            investor_id,
            uuid.uuid4(),
            uuid.uuid4(),
            stale_after_minutes=0,
        )

    db.execute.assert_not_called()


def test_disable_subscription_is_guarded_by_id_and_token_hash() -> None:
    """Public unsubscribe must update only the matching subscription secret."""
    db = _CapturedSession()

    result = subscription_crud.disable_subscription(
        db,
        uuid.uuid4(),
        expected_unsubscribe_token_hash="a" * 64,
    )

    assert result is None
    assert db.commit_count == 1
    sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "alert_subscriptions.id" in sql
    assert "alert_subscriptions.unsubscribe_token_hash" in sql
    assert "enabled" in sql


def test_optional_outcome_write_leaves_transaction_ownership_with_the_caller() -> None:
    """An outcome can join its caller's transaction, unlike a pre-send claim."""
    db = _CapturedSession()

    assert delivery_crud.mark_sent(
        db,
        uuid.uuid4(),
        datetime.now(timezone.utc),
        "message-id",
        commit=False,
    ) is None
    assert db.commit_count == 0
    assert db.flush_count == 0


def test_subscription_and_rule_upserts_flush_without_committing_on_request() -> None:
    """Settings writes can join a route's transaction when explicitly requested."""
    investor_id = uuid.uuid4()
    subscription = AlertSubscription(
        id=uuid.uuid4(),
        investor_id=investor_id,
        email="alerts@example.com",
    )
    subscription_session = _WriteSession(subscription)
    saved_subscription = subscription_crud.upsert_subscription(
        subscription_session,
        investor_id=investor_id,
        email="alerts@example.com",
        commit=False,
    )
    assert saved_subscription is subscription
    assert subscription_session.commit_count == 0
    assert subscription_session.flush_count == 1

    rule = AlertRule(id=uuid.uuid4(), investor_id=investor_id)
    rule_session = _WriteSession(rule)
    saved_rule = rule_crud.upsert_default_alert_rule(
        rule_session,
        investor_id=investor_id,
        sentiment_labels=["negative"],
        min_confidence=0.75,
        enabled=True,
        commit=False,
    )
    assert saved_rule is rule
    assert rule_session.commit_count == 0
    assert rule_session.flush_count == 1


def test_claim_sql_contract_uses_failed_or_stale_conflict_takeover() -> None:
    """The direct-claim statement must retain its PostgreSQL lease guard."""
    scrape_run_id = uuid.uuid4()
    db = _CapturedSession(artifact_scrape_run_id=scrape_run_id)
    delivery_crud.claim(
        db,
        uuid.uuid4(),
        uuid.uuid4(),
        scrape_run_id,
        stale_after_minutes=15,
    )

    assert db.statement is not None
    sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (investor_id, artifact_id) DO UPDATE" in sql
    assert "alert_deliveries.status = %(status_1)s" in sql
    assert "alert_deliveries.claimed_at < now() -" in sql
    assert "sent_at" in sql
    assert db.commit_count == 1


def test_counter_sql_contract_excludes_rollups_from_the_per_run_cap() -> None:
    """Rollups do not consume the per-investor, per-run direct-alert cap."""
    statement_session = Mock()
    statement_session.scalar.return_value = 0

    assert (
        delivery_crud.count_for_run(statement_session, uuid.uuid4(), uuid.uuid4())
        == 0
    )
    statement = statement_session.scalar.call_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "alert_deliveries.artifact_id IS NOT NULL" in sql
    assert "alert_deliveries.status IN" in sql
    assert "claimed" in sql and "sent" in sql


def test_rollup_claim_sql_targets_the_partial_unique_index() -> None:
    """Rollup claims must infer the null-artifact partial unique index."""
    db = _CapturedSession()
    delivery_crud.claim_rollup(
        db,
        uuid.uuid4(),
        uuid.uuid4(),
        stale_after_minutes=15,
    )

    assert db.statement is not None
    sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (investor_id, scrape_run_id)" in sql
    assert "WHERE artifact_id IS NULL" in sql
    assert "DO UPDATE" in sql


def test_rollup_foreign_key_restricts_deleting_ledger_parents() -> None:
    """Scrape runs with rollup ledger rows must not fail a SET NULL check."""
    foreign_key = next(
        iter(AlertDelivery.__table__.c.scrape_run_id.foreign_keys)
    )
    assert foreign_key.ondelete == "RESTRICT"

    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "86d4k9m2q_restrict_alert_delivery_scrape_run.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: Union[str, None] = "86d4k9m2p"' in migration
    assert 'ondelete="RESTRICT"' in migration
    assert 'ondelete="SET NULL"' in migration


def test_subscription_and_rule_upserts_reset_and_replace_values(
    db_session: Session,
) -> None:
    """Changing email resets verification, while default rules upsert in place."""
    investor, _, _, _ = _records(db_session)
    token_hash = "a" * 64
    first = subscription_crud.upsert_subscription(
        db_session,
        investor_id=investor.id,
        email="first.alerts@example.com",
        enabled=True,
        unsubscribe_token_hash=token_hash,
    )
    requested_at = datetime.now(timezone.utc)
    verified_at = requested_at + timedelta(seconds=1)
    subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status="verified",
        verification_requested_at=requested_at,
        verified_at=verified_at,
        expected_email="first.alerts@example.com",
        expected_verification_requested_at=None,
        expected_verification_status="unverified",
    )

    replaced = subscription_crud.upsert_subscription(
        db_session,
        investor_id=investor.id,
        email="second.alerts@example.com",
    )
    assert replaced.id == first.id
    assert replaced.email == "second.alerts@example.com"
    assert replaced.verification_status == "unverified"
    assert replaced.verification_requested_at is None
    assert replaced.verified_at is None
    stored_subscription = subscription_crud.get_subscription_by_investor(
        db_session,
        investor.id,
    )
    token_subscription = (
        subscription_crud.get_subscription_by_unsubscribe_token_hash(
            db_session,
            token_hash,
        )
    )
    assert stored_subscription is not None
    assert token_subscription is not None
    assert stored_subscription.id == first.id
    assert token_subscription.id == first.id

    first_rule = rule_crud.upsert_default_alert_rule(
        db_session,
        investor_id=investor.id,
        sentiment_labels=["negative", "positive", "negative"],
        min_confidence=0.75,
        enabled=True,
    )
    replaced_rule = rule_crud.upsert_default_alert_rule(
        db_session,
        investor_id=investor.id,
        sentiment_labels=["neutral"],
        min_confidence=0.9,
        enabled=False,
    )
    assert replaced_rule.id == first_rule.id
    assert replaced_rule.sentiment_labels == ["neutral"]
    assert float(replaced_rule.min_confidence) == pytest.approx(0.9)
    assert replaced_rule.enabled is False
    stored_rule = rule_crud.get_default_alert_rule(db_session, investor.id)
    assert stored_rule is not None
    assert stored_rule.id == first_rule.id

    disabled = subscription_crud.disable_subscription(
        db_session,
        first.id,
        expected_unsubscribe_token_hash=token_hash,
    )
    assert disabled is not None
    assert disabled.enabled is False


def test_old_email_verification_cannot_verify_a_replaced_address(
    db_session: Session,
) -> None:
    """A late SES callback may not verify a newly changed subscription email."""
    investor, _, _, _ = _records(db_session)
    initial = subscription_crud.upsert_subscription(
        db_session,
        investor_id=investor.id,
        email="old.address@example.com",
    )
    pending = subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status="pending",
        expected_email=initial.email,
        expected_verification_requested_at=None,
        expected_verification_status="unverified",
    )
    assert pending is not None
    assert pending.verification_requested_at is not None
    requested_at = pending.verification_requested_at

    changed = subscription_crud.upsert_subscription(
        db_session,
        investor_id=investor.id,
        email="new.address@example.com",
    )
    late_callback = subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status="verified",
        expected_email=initial.email,
        expected_verification_requested_at=requested_at,
        expected_verification_status="pending",
    )

    assert late_callback is None
    db_session.refresh(changed)
    assert changed.email == "new.address@example.com"
    assert changed.verification_status == "unverified"
    assert changed.verified_at is None


def test_verified_subscription_rejects_a_stale_pending_downgrade(
    db_session: Session,
) -> None:
    """An older SES pending read may not downgrade a confirmed identity."""
    investor, _, _, _ = _records(db_session)
    email = "stable.address@example.com"
    subscription_crud.upsert_subscription(
        db_session,
        investor_id=investor.id,
        email=email,
    )
    pending = subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status="pending",
        expected_email=email,
        expected_verification_requested_at=None,
        expected_verification_status="unverified",
    )
    assert pending is not None
    assert pending.verification_requested_at is not None
    requested_at = pending.verification_requested_at
    verified = subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status="verified",
        expected_email=email,
        expected_verification_requested_at=requested_at,
        expected_verification_status="pending",
    )
    assert verified is not None
    assert verified.verification_status == "verified"

    stale_pending = subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status="pending",
        expected_email=email,
        expected_verification_requested_at=requested_at,
        expected_verification_status="pending",
    )

    assert stale_pending is None
    current = subscription_crud.get_subscription_by_investor(db_session, investor.id)
    assert current is not None
    assert current.verification_status == "verified"


@pytest.mark.parametrize("observed_status", ("unverified", "failed"))
def test_fresh_ses_disagreement_can_downgrade_a_verified_subscription(
    db_session: Session,
    observed_status: str,
) -> None:
    """A current SES read may correct a previously verified local identity."""
    investor, _, _, _ = _records(db_session)
    email = f"disagreement-{uuid.uuid4().hex}@example.com"
    subscription_crud.upsert_subscription(
        db_session,
        investor_id=investor.id,
        email=email,
    )
    pending = subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status="pending",
        expected_email=email,
        expected_verification_requested_at=None,
        expected_verification_status="unverified",
    )
    assert pending is not None
    assert pending.verification_requested_at is not None
    requested_at = pending.verification_requested_at
    verified = subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status="verified",
        expected_email=email,
        expected_verification_requested_at=requested_at,
        expected_verification_status="pending",
    )
    assert verified is not None

    corrected = subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status=observed_status,
        expected_email=email,
        expected_verification_requested_at=requested_at,
        expected_verification_status="verified",
    )

    assert corrected is not None
    assert corrected.verification_status == observed_status
    assert corrected.verified_at is None


def test_delivery_outcomes_are_monotonic_by_timestamp(db_session: Session) -> None:
    """A delayed delivery result cannot overwrite a newer subscription outcome."""
    investor, _, _, _ = _records(db_session)
    subscription_crud.upsert_subscription(
        db_session, investor_id=investor.id, email=investor.email
    )
    newer = datetime.now(timezone.utc)
    older = newer - timedelta(minutes=1)
    subscription_crud.record_delivery_outcome(
        db_session,
        investor_id=investor.id,
        delivery_status="sent",
        delivery_at=newer,
    )
    result = subscription_crud.record_delivery_outcome(
        db_session,
        investor_id=investor.id,
        delivery_status="rejected",
        delivery_at=older,
        error_code="MessageRejected",
    )

    assert result is not None
    assert result.last_delivery_status == "sent"
    assert result.last_delivery_error_code is None
    assert result.last_delivery_at == newer

    equal_timestamp = subscription_crud.record_delivery_outcome(
        db_session,
        investor_id=investor.id,
        delivery_status="rejected",
        delivery_at=newer,
        error_code="MessageRejected",
    )
    assert equal_timestamp is not None
    assert equal_timestamp.last_delivery_status == "sent"
    assert equal_timestamp.last_delivery_error_code is None


def test_watcher_lookup_is_distinct_across_overlapping_watchlists(
    db_session: Session,
) -> None:
    """An investor with two watchlists receives one fan-out target."""
    investor, ticker, _, _ = _records(db_session)
    second_investor = Investor(
        email=f"second-{uuid.uuid4().hex}@example.com", username="Second watcher"
    )
    watchlists = [
        Watchlist(investor_id=investor.id, name="First"),
        Watchlist(investor_id=investor.id, name="Second"),
    ]
    db_session.add(second_investor)
    db_session.flush()
    watchlists.append(Watchlist(investor_id=second_investor.id, name="Third"))
    db_session.add_all(watchlists)
    db_session.flush()
    db_session.add_all(
        [
            WatchlistTicker(watchlist_id=watchlist.id, ticker_id=ticker.id)
            for watchlist in watchlists
        ]
    )
    db_session.commit()

    assert set(watchlist_ticker_crud.investor_ids_watching(db_session, ticker.id)) == {
        investor.id,
        second_investor.id,
    }


def test_direct_claim_skips_fresh_duplicates_and_takes_over_stale_claims(
    db_session: Session,
) -> None:
    """Fresh leases are protected, while expired claims are safely retried."""
    investor, _, scrape_run, artifact = _records(db_session)
    first = delivery_crud.claim(db_session, investor.id, artifact.id, scrape_run.id)
    assert first is not None
    stored_delivery = delivery_crud.get_delivery(db_session, first.id)
    assert stored_delivery is not None
    assert stored_delivery.id == first.id
    assert (
        delivery_crud.claim(db_session, investor.id, artifact.id, scrape_run.id)
        is None
    )

    stale_at = datetime.now(timezone.utc) - timedelta(minutes=16)
    db_session.execute(
        update(AlertDelivery)
        .where(AlertDelivery.id == first.id)
        .values(claimed_at=stale_at)
    )
    db_session.commit()
    replacement = delivery_crud.claim(
        db_session,
        investor.id,
        artifact.id,
        scrape_run.id,
        stale_after_minutes=15,
    )

    assert replacement is not None
    assert replacement.id == first.id
    assert replacement.claimed_at > stale_at


def test_claim_rejects_an_artifact_from_a_different_scrape_run(
    db_session: Session,
) -> None:
    """The ledger may not record an artifact against an unrelated run."""
    investor, _, scrape_run, artifact = _records(db_session)
    other_run = ScrapeRun(platform_id=scrape_run.platform_id, status="completed")
    db_session.add(other_run)
    db_session.flush()

    with pytest.raises(ValueError, match="scrape_run_id"):
        delivery_crud.claim(
            db_session,
            investor.id,
            artifact.id,
            other_run.id,
        )


def test_committed_claim_is_detached_but_its_lease_values_are_usable(
    db_session: Session,
) -> None:
    """A mandatory commit returns the IDs and lease timestamp callers need next."""
    investor, _, scrape_run, artifact = _records(db_session)
    claim = delivery_crud.claim(db_session, investor.id, artifact.id, scrape_run.id)

    assert claim is not None
    assert object_session(claim) is None
    assert claim.id
    assert claim.claimed_at.tzinfo is not None

    sent = delivery_crud.mark_sent(
        db_session,
        claim.id,
        claim.claimed_at,
        "detached-message",
    )
    assert sent is not None
    assert sent.status == "sent"


def test_lease_protection_blocks_late_outcomes_and_sent_rows_are_final(
    db_session: Session,
) -> None:
    """Only the current lease holder may finish a claim, and sent rows stay final."""
    investor, _, scrape_run, artifact = _records(db_session)
    claim = delivery_crud.claim(db_session, investor.id, artifact.id, scrape_run.id)
    assert claim is not None

    assert (
        delivery_crud.mark_sent(
            db_session,
            claim.id,
            claim.claimed_at - timedelta(seconds=1),
            "late-message",
        )
        is None
    )
    sent = delivery_crud.mark_sent(
        db_session, claim.id, claim.claimed_at, "message-id"
    )
    assert sent is not None and sent.status == "sent"
    assert sent.ses_message_id == "message-id"
    assert (
        delivery_crud.mark_rejected(
            db_session, sent.id, claim.claimed_at, "MessageRejected"
        )
        is None
    )
    assert (
        delivery_crud.claim(db_session, investor.id, artifact.id, scrape_run.id)
        is None
    )


def test_failed_claims_retry_immediately_and_suppressions_are_terminal(
    db_session: Session,
) -> None:
    """Retryable failures can reclaim immediately, unlike cap and budget outcomes."""
    investor, ticker, scrape_run, artifact = _records(db_session)
    failed = delivery_crud.claim(db_session, investor.id, artifact.id, scrape_run.id)
    assert failed is not None
    assert delivery_crud.mark_failed(
        db_session, failed.id, failed.claimed_at, "Throttling"
    ) is not None
    retry = delivery_crud.claim(db_session, investor.id, artifact.id, scrape_run.id)
    assert retry is not None and retry.id == failed.id

    rejected_artifact = _artifact_for_run(db_session, ticker.id, scrape_run.id)
    rejected_claim = delivery_crud.claim(
        db_session,
        investor.id,
        rejected_artifact.id,
        scrape_run.id,
    )
    assert rejected_claim is not None
    rejected = delivery_crud.mark_rejected(
        db_session,
        rejected_claim.id,
        rejected_claim.claimed_at,
        "MessageRejected",
        "SES rejected the destination",
    )
    assert rejected is not None and rejected.status == "rejected"
    assert rejected.error_code == "MessageRejected"

    cap_artifact = _artifact_for_run(db_session, ticker.id, scrape_run.id)
    cap_claim = delivery_crud.claim(
        db_session, investor.id, cap_artifact.id, scrape_run.id
    )
    assert cap_claim is not None
    capped = delivery_crud.mark_suppressed_cap(
        db_session, cap_claim.id, cap_claim.claimed_at
    )
    assert capped is not None and capped.status == "suppressed_cap"
    assert capped.error_code == "per_run_cap"
    assert delivery_crud.claim(
        db_session, investor.id, cap_artifact.id, scrape_run.id
    ) is None

    budget_artifact = _artifact_for_run(db_session, ticker.id, scrape_run.id)
    budget_claim = delivery_crud.claim(
        db_session, investor.id, budget_artifact.id, scrape_run.id
    )
    assert budget_claim is not None
    budgeted = delivery_crud.mark_suppressed_budget(
        db_session, budget_claim.id, budget_claim.claimed_at
    )
    assert budgeted is not None and budgeted.status == "suppressed_budget"
    assert budgeted.error_code == "daily_budget"


def test_run_and_daily_counters_handle_direct_and_rollup_sends(
    db_session: Session,
) -> None:
    """Run caps ignore rollups, while the daily budget counts both sent forms."""
    sent_before = delivery_crud.count_sent_last_24h(db_session)
    commitments_before = delivery_crud.count_budget_commitments_last_24h(
        db_session
    )
    investor, ticker, scrape_run, artifact = _records(db_session)
    direct_claim = delivery_crud.claim(
        db_session, investor.id, artifact.id, scrape_run.id
    )
    assert direct_claim is not None
    direct_sent = delivery_crud.mark_sent(
        db_session, direct_claim.id, direct_claim.claimed_at, "direct-message"
    )
    assert direct_sent is not None and direct_sent.status == "sent"

    active_artifact = _artifact_for_run(db_session, ticker.id, scrape_run.id)
    assert delivery_crud.claim(
        db_session, investor.id, active_artifact.id, scrape_run.id
    ) is not None
    rollup = delivery_crud.claim_rollup(db_session, investor.id, scrape_run.id)
    assert rollup is not None
    rollup_sent = delivery_crud.mark_sent(
        db_session, rollup.id, rollup.claimed_at, "rollup-message"
    )
    assert rollup_sent is not None and rollup_sent.status == "rollup_sent"

    assert delivery_crud.count_for_run(db_session, investor.id, scrape_run.id) == 2
    assert delivery_crud.count_sent_last_24h(db_session) == sent_before + 2
    assert (
        delivery_crud.count_budget_commitments_last_24h(db_session)
        == commitments_before + 3
    )
    assert delivery_crud.claim_rollup(db_session, investor.id, scrape_run.id) is None
