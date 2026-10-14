"""Database access for investor alert subscriptions."""

# pylint: disable=not-callable

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import ColumnElement, case, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.alert_vocabulary import VerificationStatus
from app.models.alert_subscription import AlertSubscription
from app.services.alert_tokens import is_token_hash


def normalise_email(email: str) -> str:
    """The one form an alert address is stored and compared in.

    The address is checked with the rules every email sender uses: one
    mailbox, no display name and nothing that needs SMTPUTF8. Its domain
    is in ASCII (punycode) form, and the whole address is lower case.
    Raises ``ValueError`` for an address alerts cannot be sent to.
    """
    try:
        validated = validate_email(
            str(email).strip(),
            allow_display_name=False,
            allow_smtputf8=False,
            check_deliverability=False,
        )
    except EmailNotValidError as exc:
        raise ValueError("email must contain one valid email address") from exc
    return str(validated.ascii_email or validated.normalized).lower()


def _expected_email(email: str) -> str:
    """Require the mailbox generation a verification callback observed."""
    try:
        return normalise_email(email)
    except ValueError as exc:
        raise ValueError("expected_email must contain one valid email address") from exc


def _normalise_token_hash(token_hash: str) -> str:
    """Validate the stored SHA-256 form of an unsubscribe token."""
    if not is_token_hash(token_hash):
        raise ValueError("unsubscribe token hash must be 64 lowercase hex characters")
    return token_hash


def _aware_timestamp(value: object, *, field: str) -> datetime:
    """Reject naive timestamps before they reach a timestamptz column."""
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field} must include a timezone")
    return value


def _optional_bool(value: bool | None, *, field: str) -> bool | None:
    """Accept a boolean or omitted value, never truthy lookalikes."""
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _validate_commit(commit: bool) -> bool:
    """Validate an explicit commit mode before any write is executed."""
    if not isinstance(commit, bool):
        raise ValueError("commit must be a boolean")
    return commit


def _finish_write(db: Session, *, commit: bool) -> None:
    """Commit by default, or leave the caller's transaction open."""
    if commit:
        db.commit()
    else:
        db.flush()


def get_subscription_by_investor(
    db: Session,
    investor_id: UUID,
) -> AlertSubscription | None:
    """Return the single alert subscription for an investor."""
    return (
        db.query(AlertSubscription)
        .filter(AlertSubscription.investor_id == investor_id)
        .first()
    )


def get_subscription(
    db: Session,
    subscription_id: UUID,
) -> AlertSubscription | None:
    """Return one subscription by its opaque identifier."""
    return db.get(AlertSubscription, subscription_id)


def upsert_subscription(  # pylint: disable=too-many-arguments
    db: Session,
    *,
    investor_id: UUID,
    email: str,
    enabled: bool | None = None,
    unsubscribe_token_hash: str | None = None,
    commit: bool = True,
) -> AlertSubscription:
    """Create or update one subscription, resetting verification on email change."""
    commit = _validate_commit(commit)
    normalised_email = normalise_email(email)
    enabled = _optional_bool(enabled, field="enabled")
    normalised_hash = (
        _normalise_token_hash(unsubscribe_token_hash)
        if unsubscribe_token_hash is not None
        else None
    )
    values: dict[str, object] = {
        "investor_id": investor_id,
        "email": normalised_email,
    }
    if enabled is not None:
        values["enabled"] = enabled
    if normalised_hash is not None:
        values["unsubscribe_token_hash"] = normalised_hash

    statement = insert(AlertSubscription).values(**values)
    email_changed = AlertSubscription.email != statement.excluded.email
    updates: dict[str, object] = {
        "email": statement.excluded.email,
        "verification_status": case(
            (email_changed, "unverified"),
            else_=AlertSubscription.verification_status,
        ),
        "verification_requested_at": case(
            (email_changed, None),
            else_=AlertSubscription.verification_requested_at,
        ),
        "verified_at": case(
            (email_changed, None),
            else_=AlertSubscription.verified_at,
        ),
        "updated_at": func.now(),
    }
    if enabled is not None:
        updates["enabled"] = statement.excluded.enabled
    if normalised_hash is not None:
        updates["unsubscribe_token_hash"] = statement.excluded.unsubscribe_token_hash

    subscription_id = db.execute(
        statement.on_conflict_do_update(
            index_elements=[AlertSubscription.investor_id],
            set_=updates,
        ).returning(AlertSubscription.id)
    ).scalar_one()
    _finish_write(db, commit=commit)

    subscription = db.get(AlertSubscription, subscription_id)
    if subscription is None:
        raise RuntimeError("alert subscription disappeared after upsert")
    db.refresh(subscription)
    return subscription


@dataclass(frozen=True)
class VerificationState:
    """The address, status and request time a verification change expects to find.

    A change writes only while the subscription still holds all three, so it
    cannot undo another change it did not see.
    """

    email: str
    status: VerificationStatus
    requested_at: datetime | None

    @classmethod
    def of(cls, subscription: AlertSubscription) -> VerificationState:
        """The state ``subscription`` holds now."""
        return cls(
            email=str(subscription.email),
            status=VerificationStatus(str(subscription.verification_status)),
            requested_at=cast(datetime | None, subscription.verification_requested_at),
        )


def reserve_verification(
    db: Session,
    investor_id: UUID,
    *,
    observed: VerificationState,
    requested_at: datetime,
    commit: bool = True,
) -> AlertSubscription | None:
    """Record a verification request made at ``requested_at``, before its email goes out.

    The subscription becomes pending. Returns None, and writes nothing, when
    it no longer holds ``observed``. A verified address is never requested
    again, so it cannot lose its confirmation here.
    """
    if observed.status == VerificationStatus.VERIFIED:
        raise ValueError("a verified subscription takes no verification request")
    return _change_verification(
        db,
        investor_id,
        expected=observed,
        status=VerificationStatus.PENDING,
        requested_at=requested_at,
        verified_at=None,
        commit=commit,
    )


def fail_verification(
    db: Session,
    investor_id: UUID,
    *,
    email: str,
    requested_at: datetime,
) -> AlertSubscription | None:
    """Mark the pending request made at ``requested_at`` failed, and commit.

    The request time stays, so the resend interval still counts from it.
    Returns None when that request is no longer the pending one.
    """
    return _change_verification(
        db,
        investor_id,
        expected=VerificationState(email, VerificationStatus.PENDING, requested_at),
        status=VerificationStatus.FAILED,
        requested_at=requested_at,
        verified_at=None,
        commit=True,
    )


def confirm_verification(
    db: Session,
    investor_id: UUID,
    *,
    email: str,
    requested_at: datetime,
    verified_at: datetime,
) -> AlertSubscription | None:
    """Mark the address of the pending request made at ``requested_at`` verified, and commit.

    Returns None when that request is no longer the pending one, or the
    address changed.
    """
    return _change_verification(
        db,
        investor_id,
        expected=VerificationState(email, VerificationStatus.PENDING, requested_at),
        status=VerificationStatus.VERIFIED,
        requested_at=requested_at,
        verified_at=verified_at,
        commit=True,
    )


def _change_verification(  # pylint: disable=too-many-arguments
    db: Session,
    investor_id: UUID,
    *,
    expected: VerificationState,
    status: VerificationStatus,
    requested_at: datetime,
    verified_at: datetime | None,
    commit: bool,
) -> AlertSubscription | None:
    """Write one verification change while the subscription still holds ``expected``."""
    commit = _validate_commit(commit)
    expected_email = _expected_email(expected.email)
    requested_at = _aware_timestamp(requested_at, field="requested_at")
    if verified_at is not None:
        verified_at = _aware_timestamp(verified_at, field="verified_at")
    requested_at_matches: ColumnElement[bool]
    if expected.requested_at is None:
        requested_at_matches = AlertSubscription.verification_requested_at.is_(None)
    else:
        requested_at_matches = AlertSubscription.verification_requested_at == (
            _aware_timestamp(expected.requested_at, field="expected requested_at")
        )
    subscription_id = db.execute(
        update(AlertSubscription)
        .where(
            AlertSubscription.investor_id == investor_id,
            AlertSubscription.email == expected_email,
            AlertSubscription.verification_status == expected.status,
            requested_at_matches,
        )
        .values(
            verification_status=status,
            verification_requested_at=requested_at,
            verified_at=verified_at,
            updated_at=func.now(),
        )
        .returning(AlertSubscription.id)
    ).scalar_one_or_none()
    _finish_write(db, commit=commit)
    if subscription_id is None:
        return None

    subscription = db.get(AlertSubscription, subscription_id)
    if subscription is None:
        raise RuntimeError("alert subscription disappeared after verification update")
    db.refresh(subscription)
    return subscription


def get_subscription_by_unsubscribe_token_hash(
    db: Session,
    unsubscribe_token_hash: str,
) -> AlertSubscription | None:
    """Resolve a subscription from a strictly validated SHA-256 token hash."""
    token_hash = _normalise_token_hash(unsubscribe_token_hash)
    return (
        db.query(AlertSubscription)
        .filter(AlertSubscription.unsubscribe_token_hash == token_hash)
        .first()
    )


def disable_subscription(
    db: Session,
    subscription_id: UUID,
    *,
    expected_unsubscribe_token_hash: str,
    commit: bool = True,
) -> AlertSubscription | None:
    """Disable a subscription only while its unsubscribe secret still matches."""
    commit = _validate_commit(commit)
    token_hash = _normalise_token_hash(expected_unsubscribe_token_hash)
    stored_id = db.execute(
        update(AlertSubscription)
        .where(
            AlertSubscription.id == subscription_id,
            AlertSubscription.unsubscribe_token_hash == token_hash,
        )
        .values(enabled=False, updated_at=func.now())
        .returning(AlertSubscription.id)
    ).scalar_one_or_none()
    _finish_write(db, commit=commit)
    if stored_id is None:
        return None

    subscription = db.get(AlertSubscription, stored_id)
    if subscription is None:
        raise RuntimeError("alert subscription disappeared after disabling")
    db.refresh(subscription)
    return subscription
