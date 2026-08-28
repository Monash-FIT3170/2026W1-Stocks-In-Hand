"""Investor notification preferences and public unsubscribe endpoints."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import cast
from uuid import UUID

from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_investor
from app.core.config import settings
from app.crud import alert_rule as alert_rule_crud
from app.crud import alert_subscription as alert_subscription_crud
from app.database.connection import get_db
from app.models.alert_rule import AlertRule
from app.models.alert_subscription import AlertSubscription
from app.models.investor import Investor
from app.schemas.notification import (
    NotificationPreferencesResponse,
    NotificationPreferencesUpdate,
    SentimentLabel,
    UnsubscribeRequest,
    UnsubscribeResponse,
    VerificationStatus,
)
from app.services import ses_alerts
from app.services.unsubscribe_tokens import (
    subscription_id_from_signed_token,
    verify_signed_unsubscribe_token,
)


router = APIRouter(prefix="/notifications", tags=["notifications"])
LOGGER = logging.getLogger(__name__)
VERIFICATION_RESEND_INTERVAL = timedelta(minutes=1)
UNSUBSCRIBE_MESSAGE = "If the token was valid, notifications are now disabled."
_DUMMY_TOKEN_HASH = "0" * 64


def _aware_utc(value: datetime) -> datetime:
    """Return one timestamp as an aware UTC value."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _preference_response(
    *,
    investor: Investor,
    subscription: AlertSubscription | None,
    rule: AlertRule | None,
    unsubscribe_token: str | None = None,
) -> NotificationPreferencesResponse:
    """Build one stable response from optional persisted preference rows."""
    labels = (
        [cast(SentimentLabel, str(label)) for label in rule.sentiment_labels]
        if rule is not None
        else [cast(SentimentLabel, "negative")]
    )
    return NotificationPreferencesResponse(
        feature_enabled=settings.NOTIFICATIONS_ENABLED,
        enabled=bool(
            subscription is not None
            and subscription.enabled
            and rule is not None
            and rule.enabled
        ),
        email=str(subscription.email if subscription is not None else investor.email),
        min_confidence=float(rule.min_confidence) if rule is not None else (
            settings.ALERT_DEFAULT_MIN_CONFIDENCE
        ),
        sentiment_labels=labels,
        verification_status=cast(
            VerificationStatus,
            str(subscription.verification_status)
            if subscription is not None
            else "unverified",
        ),
        verification_requested_at=(
            cast(datetime | None, subscription.verification_requested_at)
            if subscription is not None
            else None
        ),
        verified_at=(
            cast(datetime | None, subscription.verified_at)
            if subscription is not None
            else None
        ),
        last_delivery_status=(
            cast(str | None, subscription.last_delivery_status)
            if subscription is not None
            else None
        ),
        last_delivery_error_code=(
            cast(str | None, subscription.last_delivery_error_code)
            if subscription is not None
            else None
        ),
        last_delivery_at=(
            cast(datetime | None, subscription.last_delivery_at)
            if subscription is not None
            else None
        ),
        unsubscribe_token=unsubscribe_token,
    )


def _load_preferences(
    db: Session,
    investor_id: UUID,
) -> tuple[AlertSubscription | None, AlertRule | None]:
    """Load the two rows that form one investor's preference document."""
    return (
        alert_subscription_crud.get_subscription_by_investor(db, investor_id),
        alert_rule_crud.get_default_alert_rule(db, investor_id),
    )


def _refresh_pending_verification(
    db: Session,
    subscription: AlertSubscription | None,
) -> AlertSubscription | None:
    """Refresh a pending SES identity without failing the settings page."""
    if (
        not settings.NOTIFICATIONS_ENABLED
        or subscription is None
        or str(subscription.verification_status) != "pending"
    ):
        return subscription

    investor_id = cast(UUID, subscription.investor_id)
    email = str(subscription.email)
    requested_at = cast(datetime | None, subscription.verification_requested_at)
    db.rollback()
    try:
        refreshed_status = ses_alerts.identity_status(email)
    except (BotoCoreError, ClientError, ValueError) as exc:
        LOGGER.warning(
            "SES verification refresh failed error_code=%s",
            type(exc).__name__,
        )
        return alert_subscription_crud.get_subscription_by_investor(
            db,
            investor_id,
        )

    if refreshed_status not in {"unverified", "pending", "verified", "failed"}:
        return alert_subscription_crud.get_subscription_by_investor(db, investor_id)
    if refreshed_status == "pending":
        return alert_subscription_crud.get_subscription_by_investor(db, investor_id)

    updated = alert_subscription_crud.update_verification_state(
        db,
        investor_id=investor_id,
        verification_status=refreshed_status,
        expected_verification_status="pending",
        expected_email=email,
        expected_verification_requested_at=requested_at,
    )
    return updated or alert_subscription_crud.get_subscription_by_investor(
        db,
        investor_id,
    )


def _require_notifications_enabled() -> None:
    """Reject cost-bearing operations while the deployment switch is off."""
    if not settings.NOTIFICATIONS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notifications are not enabled",
        )


def _request_verification(email: str) -> None:
    """Request SES verification without exposing provider error details."""
    try:
        ses_alerts.request_verification(email)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The account email cannot be verified",
        ) from exc
    except (BotoCoreError, ClientError) as exc:
        LOGGER.error(
            "SES verification request failed error_code=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The verification service is unavailable",
        ) from exc


@router.get("/preferences", response_model=NotificationPreferencesResponse)
def get_notification_preferences(
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
) -> NotificationPreferencesResponse:
    """Return current preferences and refresh a pending SES identity."""
    subscription, rule = _load_preferences(db, current_investor.id)
    subscription = _refresh_pending_verification(db, subscription)
    return _preference_response(
        investor=current_investor,
        subscription=subscription,
        rule=rule,
    )


@router.put("/preferences", response_model=NotificationPreferencesResponse)
def update_notification_preferences(  # pylint: disable=too-many-locals
    body: NotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
) -> NotificationPreferencesResponse:
    """Atomically update preferences and start verification when required."""
    existing = alert_subscription_crud.get_subscription_by_investor(
        db,
        current_investor.id,
    )
    account_email = str(current_investor.email).strip().lower()
    existing_email = str(existing.email).strip().lower() if existing else None
    existing_status = str(existing.verification_status) if existing else "unverified"
    token_hash = str(existing.unsubscribe_token_hash) if (
        existing is not None and existing.unsubscribe_token_hash
    ) else None
    requires_verification = bool(
        body.enabled
        and (existing_email != account_email or existing_status != "verified")
    )
    if body.enabled:
        _require_notifications_enabled()
    if requires_verification:
        db.rollback()
        _request_verification(account_email)

    raw_token: str | None = None
    if body.enabled and token_hash is None:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    try:
        subscription = alert_subscription_crud.upsert_subscription(
            db,
            investor_id=current_investor.id,
            email=account_email,
            enabled=body.enabled,
            unsubscribe_token_hash=token_hash,
            commit=False,
        )
        rule = alert_rule_crud.upsert_default_alert_rule(
            db,
            investor_id=current_investor.id,
            sentiment_labels=body.sentiment_labels,
            min_confidence=body.min_confidence,
            enabled=body.enabled,
            commit=False,
        )
        if requires_verification and str(subscription.verification_status) != "verified":
            requested_at = datetime.now(timezone.utc)
            updated = alert_subscription_crud.update_verification_state(
                db,
                investor_id=current_investor.id,
                verification_status="pending",
                expected_verification_status=str(subscription.verification_status),
                expected_email=str(subscription.email),
                expected_verification_requested_at=cast(
                    datetime | None,
                    subscription.verification_requested_at,
                ),
                verification_requested_at=requested_at,
                commit=False,
            )
            if updated is not None:
                subscription = updated
            else:
                current = alert_subscription_crud.get_subscription_by_investor(
                    db,
                    current_investor.id,
                )
                if current is None or str(current.verification_status) != "verified":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Notification preferences changed concurrently",
                    )
                subscription = current
        db.commit()
        db.refresh(subscription)
        db.refresh(rule)
    except Exception:
        db.rollback()
        raise

    return _preference_response(
        investor=current_investor,
        subscription=subscription,
        rule=rule,
        unsubscribe_token=raw_token,
    )


@router.post(
    "/preferences/resend-verification",
    response_model=NotificationPreferencesResponse,
)
def resend_notification_verification(
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
) -> NotificationPreferencesResponse:
    """Reserve and issue at most one SES verification request per minute."""
    _require_notifications_enabled()
    subscription, rule = _load_preferences(db, current_investor.id)
    if subscription is None or not subscription.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enable notifications before requesting verification",
        )
    if str(subscription.verification_status) == "verified":
        return _preference_response(
            investor=current_investor,
            subscription=subscription,
            rule=rule,
        )

    now = datetime.now(timezone.utc)
    previous_request = cast(
        datetime | None,
        subscription.verification_requested_at,
    )
    if previous_request is not None:
        retry_after = VERIFICATION_RESEND_INTERVAL - (
            now - _aware_utc(previous_request)
        )
        if retry_after.total_seconds() > 0:
            seconds = max(ceil(retry_after.total_seconds()), 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Verification was requested recently",
                headers={"Retry-After": str(seconds)},
            )

    email = str(subscription.email)
    expected_status = str(subscription.verification_status)
    reserved = alert_subscription_crud.update_verification_state(
        db,
        investor_id=current_investor.id,
        verification_status="pending",
        expected_verification_status=expected_status,
        expected_email=email,
        expected_verification_requested_at=previous_request,
        verification_requested_at=now,
    )
    if reserved is None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Verification was requested recently",
            headers={"Retry-After": "60"},
        )

    reserved_id = cast(UUID, reserved.id)
    db.rollback()
    try:
        _request_verification(email)
    except HTTPException:
        alert_subscription_crud.update_verification_state(
            db,
            investor_id=current_investor.id,
            verification_status="failed",
            expected_verification_status="pending",
            expected_email=email,
            expected_verification_requested_at=now,
            verification_requested_at=now,
        )
        raise

    refreshed = alert_subscription_crud.get_subscription(db, reserved_id)
    return _preference_response(
        investor=current_investor,
        subscription=refreshed or reserved,
        rule=rule,
    )


def _disable_with_unsubscribe_token(db: Session, token: str) -> None:
    """Disable one matching raw or signed token without revealing the result."""
    signed_subscription_id = subscription_id_from_signed_token(token)
    if signed_subscription_id is not None:
        subscription = alert_subscription_crud.get_subscription(
            db,
            signed_subscription_id,
        )
        stored_hash = str(subscription.unsubscribe_token_hash) if (
            subscription is not None and subscription.unsubscribe_token_hash
        ) else _DUMMY_TOKEN_HASH
        verified_id = verify_signed_unsubscribe_token(token, stored_hash)
        if subscription is not None and verified_id == signed_subscription_id:
            alert_subscription_crud.disable_subscription(
                db,
                signed_subscription_id,
                expected_unsubscribe_token_hash=stored_hash,
            )
        return

    candidate_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    subscription = alert_subscription_crud.get_subscription_by_unsubscribe_token_hash(
        db,
        candidate_hash,
    )
    stored_hash = str(subscription.unsubscribe_token_hash) if (
        subscription is not None and subscription.unsubscribe_token_hash
    ) else _DUMMY_TOKEN_HASH
    if hmac.compare_digest(candidate_hash, stored_hash) and subscription is not None:
        alert_subscription_crud.disable_subscription(
            db,
            subscription.id,
            expected_unsubscribe_token_hash=stored_hash,
        )


@router.post("/unsubscribe", response_model=UnsubscribeResponse)
def unsubscribe_notifications(
    body: UnsubscribeRequest,
    db: Session = Depends(get_db),
) -> UnsubscribeResponse:
    """Disable a matching subscription and always return the same response."""
    _disable_with_unsubscribe_token(db, body.token)
    return UnsubscribeResponse(message=UNSUBSCRIBE_MESSAGE)
