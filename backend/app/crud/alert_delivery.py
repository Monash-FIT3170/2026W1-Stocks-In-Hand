"""The delivery ledger: one row for each alert or rollup an investor may get.

A row is claimed before its email is sent, and then records what became of
it: sent, rejected, failed or suppressed. A direct alert's row belongs to one
investor and artifact, and a rollup's row to one investor and scrape run, with
no artifact. Each claim is committed on its own before anything is sent, so
an email goes out at most once for each row, and every count here includes
every claim other workers have committed.

Recording an outcome also mirrors it onto the investor's alert subscription
(``last_delivery_status``, ``last_delivery_error_code`` and
``last_delivery_at``) in the same transaction, unless the subscription already
shows a newer outcome.
"""

# SQLAlchemy's dynamic ``func`` namespace confuses Pylint's call checker.
# pylint: disable=not-callable

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.alert_vocabulary import DeliveryKind, DeliveryStatus
from app.models.alert_delivery import AlertDelivery
from app.models.alert_subscription import AlertSubscription
from app.models.artifact import Artifact


_CODE_LIMIT = 128
_DETAIL_LIMIT = 2_000
_MESSAGE_ID_LIMIT = 512
_SENT = (DeliveryStatus.SENT, DeliveryStatus.ROLLUP_SENT)


@dataclass(frozen=True)
class Lease:
    """A claim an attempt holds on one ledger row, needed to record its outcome."""

    delivery_id: UUID
    investor_id: UUID
    scrape_run_id: UUID
    artifact_id: UUID | None
    claimed_at: datetime

    @property
    def kind(self) -> DeliveryKind:
        """A rollup's row is the one with no artifact."""
        return DeliveryKind.ROLLUP if self.artifact_id is None else DeliveryKind.DIRECT


@dataclass(frozen=True)
class Held:
    """A claim another row holder kept: that row's status, or None if it is gone."""

    status: DeliveryStatus | None


@dataclass(frozen=True)
class Outcome:
    """What became of a leased delivery, as the ledger records it."""

    status: DeliveryStatus
    code: str | None = None
    detail: str | None = None
    provider_message_id: str | None = None

    @classmethod
    def sent(cls, provider_message_id: str) -> Outcome:
        """The provider took the email. Its message id must not be empty."""
        message_id = provider_message_id.strip()
        if not message_id:
            raise ValueError("provider_message_id must not be empty")
        return cls(
            DeliveryStatus.SENT,
            provider_message_id=message_id[:_MESSAGE_ID_LIMIT],
        )

    @classmethod
    def rejected(cls, code: str, detail: str) -> Outcome:
        """The email will never be sent."""
        return cls(DeliveryStatus.REJECTED, code, detail)

    @classmethod
    def failed(
        cls,
        code: str,
        detail: str = "A temporary notification dependency failed",
    ) -> Outcome:
        """The email was not sent this time, and a later claim may try again."""
        return cls(DeliveryStatus.FAILED, code, detail)

    @classmethod
    def suppressed_by_cap(cls, detail: str) -> Outcome:
        """The investor reached the per-run cap, so the run's rollup stands in."""
        return cls(DeliveryStatus.SUPPRESSED_CAP, "per_run_cap", detail)

    @classmethod
    def suppressed_by_budget(cls, detail: str) -> Outcome:
        """The account reached its daily budget, so the alert is dropped for good."""
        return cls(DeliveryStatus.SUPPRESSED_BUDGET, "daily_budget", detail)


class LeaseLost(RuntimeError):
    """The row is no longer claimed under this lease, so nothing was recorded."""

    code = "delivery_lease_lost"


class SubscriptionGone(RuntimeError):
    """The investor has no subscription to mirror onto, so nothing was recorded."""

    code = "subscription_state_changed"


def _trim(value: str | None, limit: int) -> str | None:
    """Strip an optional error value and keep its stored size bounded."""
    if value is None:
        return None
    return value.strip()[:limit] or None


def claim(  # pylint: disable=too-many-arguments
    db: Session,
    kind: DeliveryKind,
    *,
    investor_id: UUID,
    scrape_run_id: UUID,
    artifact_id: UUID | None = None,
    rule_id: UUID | None = None,
    stale_after: timedelta = timedelta(minutes=15),
) -> Lease | Held:
    """Claim a delivery and commit, or say which status holds its row.

    A new row is claimed, and so is a failed one, or a claim older than
    ``stale_after`` whose worker is taken to have stopped. A direct alert
    names its artifact, which must belong to ``scrape_run_id``. A rollup has
    no artifact.
    """
    if stale_after <= timedelta(0):
        raise ValueError("stale_after must be positive")
    if scrape_run_id is None:
        raise ValueError("scrape_run_id is required for an alert claim")
    if kind is DeliveryKind.DIRECT and artifact_id is None:
        raise ValueError("artifact_id is required for a direct alert claim")
    if kind is DeliveryKind.ROLLUP and artifact_id is not None:
        raise ValueError("a rollup claim has no artifact_id")

    claimed_at = func.now()
    statement = insert(AlertDelivery).values(
        investor_id=investor_id,
        artifact_id=artifact_id,
        scrape_run_id=scrape_run_id,
        rule_id=rule_id,
        status=DeliveryStatus.CLAIMED,
        claimed_at=claimed_at,
    )
    takeover = {
        "rule_id": rule_id,
        "status": DeliveryStatus.CLAIMED,
        "claimed_at": claimed_at,
        "provider_message_id": None,
        "error_code": None,
        "error_detail": None,
        "sent_at": None,
    }
    reclaimable = or_(
        AlertDelivery.status == DeliveryStatus.FAILED,
        (AlertDelivery.status == DeliveryStatus.CLAIMED)
        & (AlertDelivery.claimed_at < claimed_at - stale_after),
    )
    if kind is DeliveryKind.DIRECT:
        artifact_scrape_run_id = db.scalar(
            select(Artifact.scrape_run_id)
            .where(Artifact.id == artifact_id)
            .with_for_update(read=True)
        )
        if artifact_scrape_run_id is None:
            raise ValueError("artifact must belong to a scrape run")
        if artifact_scrape_run_id != scrape_run_id:
            raise ValueError("scrape_run_id must match the artifact's scrape run")
        statement = statement.on_conflict_do_update(
            index_elements=[AlertDelivery.investor_id, AlertDelivery.artifact_id],
            set_=takeover,
            where=reclaimable,
        )
        same_row = AlertDelivery.artifact_id == artifact_id
    else:
        statement = statement.on_conflict_do_update(
            index_elements=[AlertDelivery.investor_id, AlertDelivery.scrape_run_id],
            index_where=AlertDelivery.artifact_id.is_(None),
            set_=takeover,
            where=reclaimable,
        )
        same_row = (AlertDelivery.scrape_run_id == scrape_run_id) & (
            AlertDelivery.artifact_id.is_(None)
        )

    claimed = db.execute(
        statement.returning(AlertDelivery.id, AlertDelivery.claimed_at)
    ).one_or_none()
    db.commit()
    if claimed is not None:
        return Lease(
            delivery_id=claimed.id,
            investor_id=investor_id,
            scrape_run_id=scrape_run_id,
            artifact_id=artifact_id,
            claimed_at=claimed.claimed_at,
        )
    status = db.scalar(
        select(AlertDelivery.status).where(
            AlertDelivery.investor_id == investor_id,
            same_row,
        )
    )
    return Held(None if status is None else DeliveryStatus(status))


def record(
    db: Session,
    lease: Lease,
    outcome: Outcome,
    *,
    at: datetime | None = None,
) -> DeliveryStatus:
    """Record a leased delivery's outcome, mirror it onto the subscription, and commit.

    A rollup's send is stored as ``rollup_sent``. The subscription takes the
    outcome only when ``at``, now by default, is later than the outcome it
    shows. Raises ``LeaseLost`` when the row is no longer claimed under this
    lease, and ``SubscriptionGone`` when the investor has no subscription.
    Either way nothing is written.
    """
    if at is None:
        at = datetime.now(timezone.utc)
    elif at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("at must include a timezone")
    status = outcome.status
    if status is DeliveryStatus.SENT and lease.kind is DeliveryKind.ROLLUP:
        status = DeliveryStatus.ROLLUP_SENT
    code = _trim(outcome.code, _CODE_LIMIT)

    with db.begin_nested():
        recorded = db.execute(
            update(AlertDelivery)
            .where(
                AlertDelivery.id == lease.delivery_id,
                AlertDelivery.status == DeliveryStatus.CLAIMED,
                AlertDelivery.claimed_at == lease.claimed_at,
            )
            .values(
                status=status,
                provider_message_id=outcome.provider_message_id,
                error_code=code,
                error_detail=_trim(outcome.detail, _DETAIL_LIMIT),
                sent_at=func.now() if status in _SENT else None,
            )
            .returning(AlertDelivery.id)
        ).scalar_one_or_none()
        if recorded is None:
            raise LeaseLost("Delivery claim was replaced before its outcome commit")
        mirrored = db.execute(
            update(AlertSubscription)
            .where(
                AlertSubscription.investor_id == lease.investor_id,
                (AlertSubscription.last_delivery_at.is_(None))
                | (AlertSubscription.last_delivery_at < at),
            )
            .values(
                last_delivery_status=status,
                last_delivery_error_code=code,
                last_delivery_at=at,
                updated_at=func.now(),
            )
            .returning(AlertSubscription.id)
        ).scalar_one_or_none()
        if mirrored is None and db.scalar(
            select(AlertSubscription.id).where(
                AlertSubscription.investor_id == lease.investor_id
            )
        ) is None:
            raise SubscriptionGone("Subscription disappeared before its outcome commit")
    db.commit()
    return status


def over_run_cap(db: Session, lease: Lease, cap: int) -> bool:
    """Whether the investor's direct alerts in the lease's run exceed ``cap``.

    It counts the alerts claimed or sent, the lease's own among them, and
    leaves out rollups.
    """
    count = db.scalar(
        select(func.count(AlertDelivery.id)).where(
            AlertDelivery.investor_id == lease.investor_id,
            AlertDelivery.scrape_run_id == lease.scrape_run_id,
            AlertDelivery.artifact_id.is_not(None),
            AlertDelivery.status.in_((DeliveryStatus.CLAIMED, DeliveryStatus.SENT)),
        )
    )
    return int(count or 0) > cap


def over_daily_budget(db: Session, budget: int) -> bool:
    """Whether the alerts sent and claims held in the last 24 hours exceed ``budget``.

    It counts every investor's alerts and rollups. A caller holding a claim is
    counted too, so its claim may take the budget's last place.
    """
    since = func.now() - timedelta(hours=24)
    count = db.scalar(
        select(func.count(AlertDelivery.id)).where(
            or_(
                (AlertDelivery.status == DeliveryStatus.CLAIMED)
                & (AlertDelivery.claimed_at >= since),
                AlertDelivery.status.in_(_SENT) & (AlertDelivery.sent_at >= since),
            )
        )
    )
    return int(count or 0) > budget


def capped_count(db: Session, lease: Lease) -> int:
    """How many of the investor's direct alerts in the lease's run the cap suppressed."""
    statement = select(func.count(AlertDelivery.id)).where(
        AlertDelivery.investor_id == lease.investor_id,
        AlertDelivery.scrape_run_id == lease.scrape_run_id,
        AlertDelivery.artifact_id.is_not(None),
        AlertDelivery.status == DeliveryStatus.SUPPRESSED_CAP,
    )
    return int(db.scalar(statement) or 0)
