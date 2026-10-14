"""Focused contracts for the alert CRUD modules and the delivery ledger.

The pure tests cover validation and commit behaviour without a database.
Integration tests use the configured Postgres database when it is
available, and otherwise skip cleanly for local runs without Docker.
"""

# pylint: disable=not-callable,redefined-outer-name,too-many-locals,wrong-import-position

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from sqlalchemy import and_, create_engine, func, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alert_vocabulary import DeliveryKind, DeliveryStatus
from app.core.config import settings
from app.crud import alert_delivery as ledger
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
    with pytest.raises(ValueError, match="stale_after"):
        ledger.claim(
            db,
            DeliveryKind.DIRECT,
            investor_id=investor_id,
            scrape_run_id=uuid.uuid4(),
            artifact_id=uuid.uuid4(),
            stale_after=timedelta(0),
        )
    with pytest.raises(ValueError, match="artifact_id is required"):
        ledger.claim(
            db,
            DeliveryKind.DIRECT,
            investor_id=investor_id,
            scrape_run_id=uuid.uuid4(),
        )
    with pytest.raises(ValueError, match="rollup claim has no artifact"):
        ledger.claim(
            db,
            DeliveryKind.ROLLUP,
            investor_id=investor_id,
            scrape_run_id=uuid.uuid4(),
            artifact_id=uuid.uuid4(),
        )
    with pytest.raises(ValueError, match="provider_message_id"):
        ledger.Outcome.sent("  ")
    lease = ledger.Lease(
        delivery_id=uuid.uuid4(),
        investor_id=investor_id,
        scrape_run_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        claimed_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match="timezone"):
        ledger.record(
            db,
            lease,
            ledger.Outcome.sent("message-id"),
            at=datetime.now(),
        )

    db.execute.assert_not_called()
    db.scalar.assert_not_called()


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
    """An old confirmation link may not verify a replacement email address."""
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
    stale_confirmation = subscription_crud.update_verification_state(
        db_session,
        investor_id=investor.id,
        verification_status="verified",
        expected_email=initial.email,
        expected_verification_requested_at=requested_at,
        expected_verification_status="pending",
    )

    assert stale_confirmation is None
    db_session.refresh(changed)
    assert changed.email == "new.address@example.com"
    assert changed.verification_status == "unverified"
    assert changed.verified_at is None


def test_verified_subscription_rejects_a_stale_pending_downgrade(
    db_session: Session,
) -> None:
    """An older request may not downgrade a confirmed email address."""
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
def test_current_state_change_can_downgrade_a_verified_subscription(
    db_session: Session,
    observed_status: str,
) -> None:
    """A current compare-and-set write may replace a verified local state."""
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


def _subscribe(db: Session, investor: Investor) -> None:
    """Give the investor the alert subscription outcomes are mirrored onto."""
    subscription_crud.upsert_subscription(db, investor_id=investor.id, email=investor.email)


def _claim_alert(
    db: Session,
    investor: Investor,
    artifact: Artifact,
    **options: Any,
) -> ledger.Lease | ledger.Held:
    """Claim the direct alert about ``artifact`` for ``investor``."""
    return ledger.claim(
        db,
        DeliveryKind.DIRECT,
        investor_id=investor.id,
        scrape_run_id=artifact.scrape_run_id,
        artifact_id=artifact.id,
        **options,
    )


def _claim_rollup(
    db: Session,
    investor: Investor,
    scrape_run: ScrapeRun,
) -> ledger.Lease | ledger.Held:
    """Claim the run's rollup for ``investor``."""
    return ledger.claim(
        db,
        DeliveryKind.ROLLUP,
        investor_id=investor.id,
        scrape_run_id=scrape_run.id,
    )


def _leased(claim: ledger.Lease | ledger.Held) -> ledger.Lease:
    assert isinstance(claim, ledger.Lease), claim
    return claim


def _row(db: Session, lease: ledger.Lease) -> AlertDelivery:
    """The lease's ledger row as the database holds it now."""
    row = db.get(AlertDelivery, lease.delivery_id, populate_existing=True)
    assert row is not None
    return row


def _mirror(db: Session, investor: Investor) -> tuple[object, object, object]:
    """The last outcome the investor's subscription shows."""
    subscription = subscription_crud.get_subscription_by_investor(db, investor.id)
    assert subscription is not None
    db.refresh(subscription)
    return (
        subscription.last_delivery_status,
        subscription.last_delivery_error_code,
        subscription.last_delivery_at,
    )


def _budget_used(db: Session) -> int:
    """Alerts sent and claims held in the last 24 hours, for every investor."""
    since = func.now() - timedelta(hours=24)
    return int(
        db.scalar(
            select(func.count(AlertDelivery.id)).where(
                or_(
                    and_(
                        AlertDelivery.status == "claimed",
                        AlertDelivery.claimed_at >= since,
                    ),
                    and_(
                        AlertDelivery.status.in_(("sent", "rollup_sent")),
                        AlertDelivery.sent_at >= since,
                    ),
                )
            )
        )
    )


def test_a_fresh_claim_is_held_and_a_stale_one_is_taken_over(
    db_session: Session,
) -> None:
    """Fresh leases are protected, while expired claims are safely retried."""
    investor, _, _, artifact = _records(db_session)
    first = _leased(_claim_alert(db_session, investor, artifact))
    assert first.kind is DeliveryKind.DIRECT

    def claimed_minutes_ago(minutes: int) -> datetime:
        claimed_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        db_session.execute(
            update(AlertDelivery)
            .where(AlertDelivery.id == first.delivery_id)
            .values(claimed_at=claimed_at)
        )
        db_session.commit()
        return claimed_at

    claimed_minutes_ago(14)
    assert _claim_alert(
        db_session, investor, artifact, stale_after=timedelta(minutes=15)
    ) == ledger.Held(DeliveryStatus.CLAIMED)

    stale_at = claimed_minutes_ago(16)
    replacement = _leased(
        _claim_alert(db_session, investor, artifact, stale_after=timedelta(minutes=15))
    )

    assert replacement.delivery_id == first.delivery_id
    assert replacement.claimed_at > stale_at


def test_a_claim_refuses_an_artifact_from_another_scrape_run(
    db_session: Session,
) -> None:
    """The ledger may not record an artifact against an unrelated run."""
    investor, _, scrape_run, artifact = _records(db_session)
    other_run = ScrapeRun(platform_id=scrape_run.platform_id, status="completed")
    db_session.add(other_run)
    db_session.flush()

    with pytest.raises(ValueError, match="scrape_run_id"):
        ledger.claim(
            db_session,
            DeliveryKind.DIRECT,
            investor_id=investor.id,
            scrape_run_id=other_run.id,
            artifact_id=artifact.id,
        )


def test_an_outcome_is_recorded_on_the_row_and_the_subscription_together(
    db_session: Session,
) -> None:
    """The ledger row and the subscription's last outcome change in one write."""
    investor, _, _, artifact = _records(db_session)
    _subscribe(db_session, investor)
    lease = _leased(_claim_alert(db_session, investor, artifact))
    at = datetime.now(timezone.utc)

    recorded = ledger.record(
        db_session,
        lease,
        ledger.Outcome.rejected("invalid_parameter", "Brevo rejected the destination"),
        at=at,
    )

    assert recorded is DeliveryStatus.REJECTED
    row = _row(db_session, lease)
    assert (row.status, row.error_code, row.error_detail) == (
        "rejected",
        "invalid_parameter",
        "Brevo rejected the destination",
    )
    assert _mirror(db_session, investor) == ("rejected", "invalid_parameter", at)


def test_an_outcome_without_a_subscription_is_not_recorded(
    db_session: Session,
) -> None:
    """Without a subscription to mirror onto, the ledger row keeps its claim."""
    investor, _, _, artifact = _records(db_session)
    lease = _leased(_claim_alert(db_session, investor, artifact))

    with pytest.raises(ledger.SubscriptionGone):
        ledger.record(db_session, lease, ledger.Outcome.sent("message-id"))

    row = _row(db_session, lease)
    assert (row.status, row.provider_message_id) == ("claimed", None)


def test_an_outdated_lease_records_nothing(db_session: Session) -> None:
    """Only the current lease holder may finish a claim."""
    investor, _, _, artifact = _records(db_session)
    _subscribe(db_session, investor)
    lease = _leased(_claim_alert(db_session, investor, artifact))
    outdated = replace(lease, claimed_at=lease.claimed_at - timedelta(seconds=1))

    with pytest.raises(ledger.LeaseLost):
        ledger.record(db_session, outdated, ledger.Outcome.sent("late-message"))

    row = _row(db_session, lease)
    assert (row.status, row.provider_message_id) == ("claimed", None)
    assert _mirror(db_session, investor) == (None, None, None)


def test_a_sent_alert_is_final(db_session: Session) -> None:
    """A sent row takes no other outcome and no new claim."""
    investor, _, _, artifact = _records(db_session)
    _subscribe(db_session, investor)
    lease = _leased(_claim_alert(db_session, investor, artifact))

    assert ledger.record(
        db_session, lease, ledger.Outcome.sent(" message-id ")
    ) is DeliveryStatus.SENT

    row = _row(db_session, lease)
    assert (row.status, row.provider_message_id, row.error_code) == (
        "sent",
        "message-id",
        None,
    )
    assert row.sent_at is not None
    with pytest.raises(ledger.LeaseLost):
        ledger.record(
            db_session,
            lease,
            ledger.Outcome.rejected("invalid_parameter", "Brevo rejected the destination"),
        )
    assert _claim_alert(db_session, investor, artifact) == ledger.Held(DeliveryStatus.SENT)


def test_a_failed_alert_can_be_claimed_again_at_once(db_session: Session) -> None:
    """A retry may take over a failed row without waiting for it to go stale."""
    investor, _, _, artifact = _records(db_session)
    _subscribe(db_session, investor)
    failed = _leased(_claim_alert(db_session, investor, artifact))

    assert ledger.record(
        db_session, failed, ledger.Outcome.failed("rate_limit")
    ) is DeliveryStatus.FAILED
    row = _row(db_session, failed)
    assert (row.error_code, row.error_detail) == (
        "rate_limit",
        "A temporary notification dependency failed",
    )

    retry = _leased(_claim_alert(db_session, investor, artifact))
    assert retry.delivery_id == failed.delivery_id
    row = _row(db_session, retry)
    assert (row.status, row.error_code, row.error_detail) == ("claimed", None, None)


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (
            ledger.Outcome.rejected("invalid_parameter", "Brevo rejected the destination"),
            "invalid_parameter",
        ),
        (
            ledger.Outcome.suppressed_by_cap("Investor per-run alert limit reached"),
            "per_run_cap",
        ),
        (
            ledger.Outcome.suppressed_by_budget("Account daily alert budget reached"),
            "daily_budget",
        ),
    ],
)
def test_a_rejected_or_suppressed_alert_is_final(
    db_session: Session,
    outcome: ledger.Outcome,
    code: str,
) -> None:
    """Rejections and suppressions keep their code and take no new claim."""
    investor, _, _, artifact = _records(db_session)
    _subscribe(db_session, investor)
    lease = _leased(_claim_alert(db_session, investor, artifact))

    assert ledger.record(db_session, lease, outcome) is outcome.status

    assert _row(db_session, lease).error_code == code
    assert _claim_alert(db_session, investor, artifact) == ledger.Held(outcome.status)


def test_the_cap_counts_direct_alerts_and_the_budget_counts_every_send(
    db_session: Session,
) -> None:
    """The per-run cap leaves out rollups and suppressed alerts.

    The daily budget counts direct and rollup sends and held claims alike.
    """
    used = _budget_used(db_session)
    investor, ticker, scrape_run, artifact = _records(db_session)
    _subscribe(db_session, investor)
    sent = _leased(_claim_alert(db_session, investor, artifact))
    ledger.record(db_session, sent, ledger.Outcome.sent("direct-message"))
    held = _leased(
        _claim_alert(
            db_session,
            investor,
            _artifact_for_run(db_session, ticker.id, scrape_run.id),
        )
    )
    for _ in range(2):
        capped = _leased(
            _claim_alert(
                db_session,
                investor,
                _artifact_for_run(db_session, ticker.id, scrape_run.id),
            )
        )
        ledger.record(
            db_session,
            capped,
            ledger.Outcome.suppressed_by_cap("Investor per-run alert limit reached"),
        )
    rollup = _leased(_claim_rollup(db_session, investor, scrape_run))
    assert rollup.kind is DeliveryKind.ROLLUP

    assert ledger.record(
        db_session, rollup, ledger.Outcome.sent("rollup-message")
    ) is DeliveryStatus.ROLLUP_SENT

    assert not ledger.over_run_cap(db_session, held, 2)
    assert ledger.over_run_cap(db_session, held, 1)
    assert ledger.capped_count(db_session, rollup) == 2
    assert not ledger.over_daily_budget(db_session, used + 3)
    assert ledger.over_daily_budget(db_session, used + 2)
    assert _claim_rollup(db_session, investor, scrape_run) == ledger.Held(
        DeliveryStatus.ROLLUP_SENT
    )


def test_every_committed_claim_counts_against_the_cap(db_session: Session) -> None:
    """Two workers that each claimed an alert each count the other's claim too.

    So with a cap of one, neither sends a second alert in the run, whichever
    of them checks first.
    """
    investor, ticker, scrape_run, artifact = _records(db_session)
    first = _leased(_claim_alert(db_session, investor, artifact))
    second = _leased(
        _claim_alert(
            db_session,
            investor,
            _artifact_for_run(db_session, ticker.id, scrape_run.id),
        )
    )

    assert ledger.over_run_cap(db_session, first, 1)
    assert ledger.over_run_cap(db_session, second, 1)


def test_the_subscription_keeps_the_newest_outcome(db_session: Session) -> None:
    """A delayed outcome cannot replace a newer one on the subscription."""
    investor, ticker, scrape_run, artifact = _records(db_session)
    _subscribe(db_session, investor)
    newer = datetime.now(timezone.utc)
    ledger.record(
        db_session,
        _leased(_claim_alert(db_session, investor, artifact)),
        ledger.Outcome.sent("newer-message"),
        at=newer,
    )

    for at in (newer - timedelta(minutes=1), newer):
        lease = _leased(
            _claim_alert(
                db_session,
                investor,
                _artifact_for_run(db_session, ticker.id, scrape_run.id),
            )
        )
        assert ledger.record(
            db_session,
            lease,
            ledger.Outcome.rejected("invalid_parameter", "Brevo rejected the destination"),
            at=at,
        ) is DeliveryStatus.REJECTED

    assert _mirror(db_session, investor) == ("sent", None, newer)
