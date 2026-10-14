"""Investor notification preferences and public unsubscribe endpoints.

Each route calls one operation of the alert subscription module
(``app/services/alert_subscriptions.py``) and turns the refusal it raises, if
any, into an HTTP answer.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_investor
from app.database.connection import get_db
from app.models.investor import Investor
from app.schemas.notification import (
    NotificationPreferencesResponse,
    NotificationPreferencesUpdate,
    UnsubscribeRequest,
    UnsubscribeResponse,
    VerificationRequest,
    VerificationResponse,
)
from app.services import alert_subscriptions
from app.services.alert_subscriptions import (
    AddressNotUsable,
    AlertPreferences,
    AlertsNotEnabled,
    AlertsSwitchedOff,
    AlertSubscriptionError,
    InvalidVerificationLink,
    PreferencesChangedConcurrently,
    SupersededVerificationLink,
    VerificationEmailNotSent,
    VerificationRequestedRecently,
)
from app.services.email_sender import (
    EmailSender,
    Misconfigured,
    RecipientRejected,
    SendOutcome,
    Unavailable,
    current_sender,
)


router = APIRouter(prefix="/notifications", tags=["notifications"])
UNSUBSCRIBE_MESSAGE = "If the token was valid, notifications are now disabled."
VERIFICATION_MESSAGE = "Your email address is verified for watchlist alerts."
# What a route answers for each refusal of the alert subscription module.
_REFUSALS: dict[type[AlertSubscriptionError], tuple[int, str]] = {
    AlertsSwitchedOff: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Notifications are not enabled",
    ),
    AlertsNotEnabled: (
        status.HTTP_409_CONFLICT,
        "Enable notifications before requesting verification",
    ),
    VerificationRequestedRecently: (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Verification was requested recently",
    ),
    PreferencesChangedConcurrently: (
        status.HTTP_409_CONFLICT,
        "Notification preferences changed concurrently",
    ),
    InvalidVerificationLink: (
        status.HTTP_400_BAD_REQUEST,
        "The verification link is invalid or expired.",
    ),
    SupersededVerificationLink: (
        status.HTTP_409_CONFLICT,
        "The verification request changed. Open the newest email.",
    ),
    AddressNotUsable: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The email address on your account cannot receive alerts.",
    ),
}
# What a route answers when its verification email is not sent. The investor
# can fix a refused address, a retry may reach an unavailable service, and a
# misconfiguration needs a fix on our side.
_UNSENT_VERIFICATION: dict[type[SendOutcome], tuple[int, str]] = {
    RecipientRejected: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The email service refused this address. Check the email address on your account.",
    ),
    Unavailable: (
        status.HTTP_502_BAD_GATEWAY,
        "The verification service is unavailable",
    ),
    Misconfigured: (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Email verification is not configured",
    ),
}


@contextmanager
def _refusals_answered() -> Iterator[None]:
    """Raise the HTTP answer for a refusal of the alert subscription module."""
    try:
        yield
    except VerificationEmailNotSent as exc:
        status_code, detail = _UNSENT_VERIFICATION[type(exc.outcome)]
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except AlertSubscriptionError as exc:
        status_code, detail = _REFUSALS[type(exc)]
        headers = (
            {"Retry-After": str(exc.retry_after_seconds)}
            if isinstance(exc, VerificationRequestedRecently)
            else None
        )
        raise HTTPException(status_code=status_code, detail=detail, headers=headers) from exc


def _response(
    preferences: AlertPreferences,
    unsubscribe_token: str | None = None,
) -> NotificationPreferencesResponse:
    return NotificationPreferencesResponse(
        **asdict(preferences),
        unsubscribe_token=unsubscribe_token,
    )


@router.get("/preferences", response_model=NotificationPreferencesResponse)
def get_notification_preferences(
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
) -> NotificationPreferencesResponse:
    """Return the current locally-owned alert preferences."""
    return _response(
        alert_subscriptions.read(
            db,
            investor_id=cast(UUID, current_investor.id),
            account_email=str(current_investor.email),
        )
    )


@router.put("/preferences", response_model=NotificationPreferencesResponse)
def update_notification_preferences(
    body: NotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
    sender: EmailSender = Depends(current_sender),
) -> NotificationPreferencesResponse:
    """Save preferences and send a verification link when one is due."""
    with _refusals_answered():
        saved = alert_subscriptions.save(
            db,
            investor_id=cast(UUID, current_investor.id),
            account_email=str(current_investor.email),
            enabled=body.enabled,
            sentiment_labels=body.sentiment_labels,
            min_confidence=body.min_confidence,
            sender=sender,
        )
    return _response(saved.preferences, saved.unsubscribe_token)


@router.post(
    "/preferences/resend-verification",
    response_model=NotificationPreferencesResponse,
)
def resend_notification_verification(
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
    sender: EmailSender = Depends(current_sender),
) -> NotificationPreferencesResponse:
    """Send a new verification link, at most once a minute."""
    with _refusals_answered():
        preferences = alert_subscriptions.request_verification(
            db,
            investor_id=cast(UUID, current_investor.id),
            account_email=str(current_investor.email),
            sender=sender,
        )
    return _response(preferences)


@router.post("/verify", response_model=VerificationResponse)
def verify_notification_email(
    body: VerificationRequest,
    db: Session = Depends(get_db),
) -> VerificationResponse:
    """Consume one signed, expiring alert-email confirmation token."""
    with _refusals_answered():
        alert_subscriptions.confirm(db, body.token)
    return VerificationResponse(message=VERIFICATION_MESSAGE)


@router.post("/unsubscribe", response_model=UnsubscribeResponse)
def unsubscribe_notifications(
    body: UnsubscribeRequest,
    db: Session = Depends(get_db),
) -> UnsubscribeResponse:
    """Disable a matching subscription and always return the same response."""
    alert_subscriptions.unsubscribe(db, body.token)
    return UnsubscribeResponse(message=UNSUBSCRIBE_MESSAGE)
