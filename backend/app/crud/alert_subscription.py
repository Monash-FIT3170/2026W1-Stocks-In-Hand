"""Database access for investor alert subscriptions."""

# pylint: disable=not-callable

from __future__ import annotations

import re
from datetime import datetime
from typing import Final
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import case, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.alert_subscription import AlertSubscription


VERIFICATION_STATUSES: Final[frozenset[str]] = frozenset(
    {"unverified", "pending", "verified", "failed"}
)
SHA256_HEX: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")
DELIVERY_ERROR_CODE_LIMIT: Final[int] = 128
_UNSET: Final[object] = object()


def _normalise_email(email: str) -> str:
    """Return one deliverable-independent, lower-case mailbox address."""
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
        return _normalise_email(email)
    except ValueError as exc:
        raise ValueError("expected_email must contain one valid email address") from exc


def _normalise_token_hash(token_hash: str) -> str:
    """Validate the stored SHA-256 form of an unsubscribe token."""
    if not SHA256_HEX.fullmatch(token_hash):
        raise ValueError("unsubscribe token hash must be 64 lowercase hex characters")
    return token_hash


def _verification_status(value: str) -> str:
    """Validate one persisted application confirmation status."""
    status = str(value).strip().lower()
    if status not in VERIFICATION_STATUSES:
        allowed = ", ".join(sorted(VERIFICATION_STATUSES))
        raise ValueError(f"verification status must be one of: {allowed}")
    return status


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
    normalised_email = _normalise_email(email)
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


def update_verification_state(  # pylint: disable=too-many-arguments,too-many-branches,too-many-locals
    db: Session,
    *,
    investor_id: UUID,
    verification_status: str,
    expected_verification_status: str,
    expected_email: str,
    expected_verification_requested_at: datetime | None,
    verification_requested_at: datetime | None | object = _UNSET,
    verified_at: datetime | None | object = _UNSET,
    commit: bool = True,
) -> AlertSubscription | None:
    """Apply a guarded email-confirmation transition for one subscription."""
    commit = _validate_commit(commit)
    status = _verification_status(verification_status)
    expected_status = _verification_status(expected_verification_status)
    normalised_expected_email = _expected_email(expected_email)
    if verification_requested_at is not _UNSET and verification_requested_at is not None:
        _aware_timestamp(
            verification_requested_at,
            field="verification_requested_at",
        )
    if verified_at is not _UNSET and verified_at is not None:
        _aware_timestamp(verified_at, field="verified_at")
    if expected_verification_requested_at is not None:
        _aware_timestamp(
            expected_verification_requested_at,
            field="expected_verification_requested_at",
        )
    values: dict[str, object] = {
        "verification_status": status,
        "updated_at": func.now(),
    }
    if status == "pending":
        values["verification_requested_at"] = (
            func.now()
            if verification_requested_at is _UNSET
            or verification_requested_at is None
            else _aware_timestamp(
                verification_requested_at,
                field="verification_requested_at",
            )
        )
        values["verified_at"] = None
    elif status == "verified":
        if verification_requested_at is not _UNSET:
            values["verification_requested_at"] = (
                None
                if verification_requested_at is None
                else _aware_timestamp(
                    verification_requested_at,
                    field="verification_requested_at",
                )
            )
        values["verified_at"] = (
            func.now()
            if verified_at is _UNSET or verified_at is None
            else _aware_timestamp(verified_at, field="verified_at")
        )
    else:
        if verification_requested_at is not _UNSET:
            values["verification_requested_at"] = (
                None
                if verification_requested_at is None
                else _aware_timestamp(
                    verification_requested_at,
                    field="verification_requested_at",
                )
            )
        values["verified_at"] = None

    conditions = [AlertSubscription.investor_id == investor_id]
    conditions.append(AlertSubscription.email == normalised_expected_email)
    conditions.append(AlertSubscription.verification_status == expected_status)
    if expected_verification_requested_at is None:
        conditions.append(AlertSubscription.verification_requested_at.is_(None))
    else:
        conditions.append(
            AlertSubscription.verification_requested_at
            == expected_verification_requested_at
        )
    subscription_id = db.execute(
        update(AlertSubscription)
        .where(*conditions)
        .values(**values)
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


def record_delivery_outcome(  # pylint: disable=too-many-arguments
    db: Session,
    *,
    investor_id: UUID,
    delivery_status: str,
    delivery_at: datetime,
    error_code: str | None = None,
    commit: bool = True,
) -> AlertSubscription | None:
    """Record an outcome without allowing an older event to replace a newer one."""
    commit = _validate_commit(commit)
    delivery_at = _aware_timestamp(delivery_at, field="delivery_at")
    status = str(delivery_status).strip()
    if not status:
        raise ValueError("delivery status must not be empty")
    if "\r" in status or "\n" in status:
        raise ValueError("delivery status must not contain line breaks")
    if error_code is not None and ("\r" in error_code or "\n" in error_code):
        raise ValueError("error code must not contain line breaks")
    normalised_error_code = (
        error_code.strip()[:DELIVERY_ERROR_CODE_LIMIT] or None
        if error_code is not None
        else None
    )

    subscription_id = db.execute(
        update(AlertSubscription)
        .where(
            AlertSubscription.investor_id == investor_id,
            (AlertSubscription.last_delivery_at.is_(None))
            | (AlertSubscription.last_delivery_at < delivery_at),
        )
        .values(
            last_delivery_status=status,
            last_delivery_error_code=normalised_error_code,
            last_delivery_at=delivery_at,
            updated_at=func.now(),
        )
        .returning(AlertSubscription.id)
    ).scalar_one_or_none()
    _finish_write(db, commit=commit)
    if subscription_id is None:
        return get_subscription_by_investor(db, investor_id)

    subscription = db.get(AlertSubscription, subscription_id)
    if subscription is None:
        raise RuntimeError("alert subscription disappeared after delivery update")
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
