"""Atomic claim and outcome transitions for alert deliveries."""

# The public CRUD signatures carry the IDs and lease needed for safe writes.
# SQLAlchemy's dynamic ``func`` namespace also confuses Pylint's call checker.
# pylint: disable=too-many-arguments,too-many-positional-arguments,not-callable

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from app.models.alert_delivery import AlertDelivery
from app.models.artifact import Artifact


_ERROR_CODE_LIMIT = 128
_ERROR_DETAIL_LIMIT = 2_000


def _trim(value: str | None, limit: int) -> str | None:
    """Strip an optional error value and keep its stored size bounded."""
    if value is None:
        return None
    value = value.strip()
    return value[:limit] or None


def _validate_stale_after(stale_after_minutes: int) -> timedelta:
    """Return a stale-claim interval after validating the lease duration."""
    if isinstance(stale_after_minutes, bool) or stale_after_minutes <= 0:
        raise ValueError("stale_after_minutes must be positive")
    return timedelta(minutes=stale_after_minutes)


def _validate_claim_ids(
    artifact_id: UUID | None,
    scrape_run_id: UUID | None,
) -> None:
    """Reject incomplete direct claims before they reach PostgreSQL."""
    if artifact_id is None:
        raise ValueError("artifact_id is required for a direct alert claim")
    if scrape_run_id is None:
        raise ValueError("scrape_run_id is required for an alert claim")


def _returning_delivery(
    db: Session,
    statement: Executable,
    *,
    commit: bool,
) -> AlertDelivery | None:
    """Execute a returning statement under the requested transaction boundary."""
    delivery = db.execute(
        statement.execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if commit:
        if delivery is not None:
            # Keep all returned column values usable without starting a new
            # transaction after the mandatory pre-send claim commit.
            db.expunge(delivery)
        db.commit()
    return delivery


def get_delivery(db: Session, delivery_id: UUID) -> AlertDelivery | None:
    """Return one delivery by primary key."""
    return db.get(AlertDelivery, delivery_id)


def get_for_artifact(
    db: Session,
    investor_id: UUID,
    artifact_id: UUID,
) -> AlertDelivery | None:
    """Return the direct delivery ledger row for one investor and artifact."""
    return (
        db.query(AlertDelivery)
        .filter(
            AlertDelivery.investor_id == investor_id,
            AlertDelivery.artifact_id == artifact_id,
        )
        .first()
    )


def get_rollup(
    db: Session,
    investor_id: UUID,
    scrape_run_id: UUID,
) -> AlertDelivery | None:
    """Return the rollup ledger row for one investor and scrape run."""
    return (
        db.query(AlertDelivery)
        .filter(
            AlertDelivery.investor_id == investor_id,
            AlertDelivery.scrape_run_id == scrape_run_id,
            AlertDelivery.artifact_id.is_(None),
        )
        .first()
    )


def claim(
    db: Session,
    investor_id: UUID,
    artifact_id: UUID,
    scrape_run_id: UUID,
    rule_id: UUID | None = None,
    stale_after_minutes: int = 15,
) -> AlertDelivery | None:
    """Claim a direct alert after verifying its scrape-run provenance."""
    _validate_claim_ids(artifact_id, scrape_run_id)
    stale_after = _validate_stale_after(stale_after_minutes)
    artifact_scrape_run_id = db.scalar(
        select(Artifact.scrape_run_id)
        .where(Artifact.id == artifact_id)
        .with_for_update(read=True)
    )
    if artifact_scrape_run_id is None:
        raise ValueError("artifact must belong to a scrape run")
    if artifact_scrape_run_id != scrape_run_id:
        raise ValueError("scrape_run_id must match the artifact's scrape run")
    claimed_at = func.now()
    statement = (
        insert(AlertDelivery)
        .values(
            investor_id=investor_id,
            artifact_id=artifact_id,
            scrape_run_id=scrape_run_id,
            rule_id=rule_id,
            status="claimed",
            claimed_at=claimed_at,
        )
        .on_conflict_do_update(
            index_elements=[
                AlertDelivery.investor_id,
                AlertDelivery.artifact_id,
            ],
            set_={
                "rule_id": rule_id,
                "status": "claimed",
                "claimed_at": claimed_at,
                "ses_message_id": None,
                "error_code": None,
                "error_detail": None,
                "sent_at": None,
            },
            where=or_(
                AlertDelivery.status == "failed",
                (
                    (AlertDelivery.status == "claimed")
                    & (AlertDelivery.claimed_at < claimed_at - stale_after)
                ),
            ),
        )
        .returning(AlertDelivery)
    )
    return _returning_delivery(db, statement, commit=True)


def claim_rollup(
    db: Session,
    investor_id: UUID,
    scrape_run_id: UUID,
    rule_id: UUID | None = None,
    stale_after_minutes: int = 15,
) -> AlertDelivery | None:
    """Atomically claim one rollup using its partial unique index."""
    if scrape_run_id is None:
        raise ValueError("scrape_run_id is required for a rollup claim")
    stale_after = _validate_stale_after(stale_after_minutes)
    claimed_at = func.now()
    statement = (
        insert(AlertDelivery)
        .values(
            investor_id=investor_id,
            artifact_id=None,
            scrape_run_id=scrape_run_id,
            rule_id=rule_id,
            status="claimed",
            claimed_at=claimed_at,
        )
        .on_conflict_do_update(
            index_elements=[
                AlertDelivery.investor_id,
                AlertDelivery.scrape_run_id,
            ],
            index_where=AlertDelivery.artifact_id.is_(None),
            set_={
                "rule_id": rule_id,
                "status": "claimed",
                "claimed_at": claimed_at,
                "ses_message_id": None,
                "error_code": None,
                "error_detail": None,
                "sent_at": None,
            },
            where=or_(
                AlertDelivery.status == "failed",
                (
                    (AlertDelivery.status == "claimed")
                    & (AlertDelivery.claimed_at < claimed_at - stale_after)
                ),
            ),
        )
        .returning(AlertDelivery)
    )
    return _returning_delivery(db, statement, commit=True)


def _transition(
    db: Session,
    delivery_id: UUID,
    expected_claimed_at: datetime,
    *,
    status: str | object,
    ses_message_id: str | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
    sent_at: object | None = None,
    commit: bool = True,
) -> AlertDelivery | None:
    """Apply an outcome only when the caller still owns the claim lease."""
    if not isinstance(commit, bool):
        raise ValueError("commit must be a boolean")
    statement = (
        update(AlertDelivery)
        .where(
            AlertDelivery.id == delivery_id,
            AlertDelivery.status == "claimed",
            AlertDelivery.claimed_at == expected_claimed_at,
        )
        .values(
            status=status,
            ses_message_id=ses_message_id,
            error_code=_trim(error_code, _ERROR_CODE_LIMIT),
            error_detail=_trim(error_detail, _ERROR_DETAIL_LIMIT),
            sent_at=sent_at,
        )
        .returning(AlertDelivery)
    )
    return _returning_delivery(db, statement, commit=commit)


def mark_sent(
    db: Session,
    delivery_id: UUID,
    expected_claimed_at: datetime,
    ses_message_id: str,
    *,
    commit: bool = True,
) -> AlertDelivery | None:
    """Mark a leased direct or rollup delivery as sent."""
    message_id = ses_message_id.strip()
    if not message_id:
        raise ValueError("ses_message_id must not be empty")
    return _transition(
        db,
        delivery_id,
        expected_claimed_at,
        status=case(
            (AlertDelivery.artifact_id.is_(None), "rollup_sent"),
            else_="sent",
        ),
        ses_message_id=message_id[:512],
        sent_at=func.now(),
        commit=commit,
    )


def mark_rejected(
    db: Session,
    delivery_id: UUID,
    expected_claimed_at: datetime,
    error_code: str,
    error_detail: str | None = None,
    *,
    commit: bool = True,
) -> AlertDelivery | None:
    """Record a terminal rejection while the caller owns the lease."""
    return _transition(
        db,
        delivery_id,
        expected_claimed_at,
        status="rejected",
        error_code=error_code,
        error_detail=error_detail,
        commit=commit,
    )


def mark_failed(
    db: Session,
    delivery_id: UUID,
    expected_claimed_at: datetime,
    error_code: str,
    error_detail: str | None = None,
    *,
    commit: bool = True,
) -> AlertDelivery | None:
    """Record a retryable failure while the caller owns the lease."""
    return _transition(
        db,
        delivery_id,
        expected_claimed_at,
        status="failed",
        error_code=error_code,
        error_detail=error_detail,
        commit=commit,
    )


def mark_suppressed_cap(
    db: Session,
    delivery_id: UUID,
    expected_claimed_at: datetime,
    error_detail: str | None = None,
    *,
    commit: bool = True,
) -> AlertDelivery | None:
    """Record suppression by the investor's per-run cap."""
    return _transition(
        db,
        delivery_id,
        expected_claimed_at,
        status="suppressed_cap",
        error_code="per_run_cap",
        error_detail=error_detail,
        commit=commit,
    )


def mark_suppressed_budget(
    db: Session,
    delivery_id: UUID,
    expected_claimed_at: datetime,
    error_detail: str | None = None,
    *,
    commit: bool = True,
) -> AlertDelivery | None:
    """Record suppression by the account's daily sending budget."""
    return _transition(
        db,
        delivery_id,
        expected_claimed_at,
        status="suppressed_budget",
        error_code="daily_budget",
        error_detail=error_detail,
        commit=commit,
    )


def count_for_run(db: Session, investor_id: UUID, scrape_run_id: UUID) -> int:
    """Count direct active or sent alerts against an investor's run cap."""
    statement = select(func.count(AlertDelivery.id)).where(
        AlertDelivery.investor_id == investor_id,
        AlertDelivery.scrape_run_id == scrape_run_id,
        AlertDelivery.artifact_id.is_not(None),
        AlertDelivery.status.in_(("claimed", "sent")),
    )
    return int(db.scalar(statement) or 0)


def count_sent_last_24h(db: Session) -> int:
    """Count direct and rollup messages sent during the last 24 hours."""
    statement = select(func.count(AlertDelivery.id)).where(
        AlertDelivery.status.in_(("sent", "rollup_sent")),
        AlertDelivery.sent_at >= func.now() - timedelta(hours=24),
    )
    return int(db.scalar(statement) or 0)


def count_budget_commitments_last_24h(db: Session) -> int:
    """Count recent sends and active claims reserved against the daily cap."""
    cutoff = func.now() - timedelta(hours=24)
    statement = select(func.count(AlertDelivery.id)).where(
        or_(
            (
                (AlertDelivery.status == "claimed")
                & (AlertDelivery.claimed_at >= cutoff)
            ),
            (
                AlertDelivery.status.in_(("sent", "rollup_sent"))
                & (AlertDelivery.sent_at >= cutoff)
            ),
        )
    )
    return int(db.scalar(statement) or 0)


def count_suppressed_for_run(
    db: Session,
    investor_id: UUID,
    scrape_run_id: UUID,
) -> int:
    """Count direct alerts suppressed by an investor's per-run cap."""
    statement = select(func.count(AlertDelivery.id)).where(
        AlertDelivery.investor_id == investor_id,
        AlertDelivery.scrape_run_id == scrape_run_id,
        AlertDelivery.artifact_id.is_not(None),
        AlertDelivery.status == "suppressed_cap",
    )
    return int(db.scalar(statement) or 0)
