"""Alert subscriptions: an investor's opt-in to alerts at one confirmed address.

``save`` stores an investor's alert rule. Alerts go to the investor's account
address, which must be verified first, so turning alerts on records a
verification request and emails a verification link. ``request_verification``
sends a new link at most once a minute. A request whose email is not sent is
marked failed. ``confirm`` accepts only the newest request's link, while it is
fresh. ``unsubscribe`` turns alerts off for whoever holds an unsubscribe token,
and never says whether the token matched.

Each operation commits what it writes. One that sends an email commits its
request and ends its transaction before it calls the sender, so no
transaction or row lock is held while the email service answers, and another
request already sees the new request. Refusals raise an
``AlertSubscriptionError``, which the routes turn into HTTP answers.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import cast
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy.orm import Session

from app.alert_vocabulary import DEFAULT_ALERT_SENTIMENT_LABELS, VerificationStatus
from app.core.config import settings
from app.crud import alert_rule as alert_rule_crud
from app.crud import alert_subscription as alert_subscription_crud
from app.crud.alert_subscription import VerificationState
from app.models.alert_rule import AlertRule
from app.models.alert_subscription import AlertSubscription
from app.services.alert_templates import render_verification_email
from app.services.email_sender import (
    Accepted,
    EmailSender,
    Misconfigured,
    OutgoingEmail,
    RecipientRejected,
    SendOutcome,
    Unavailable,
)
from app.services.unsubscribe_tokens import (
    subscription_id_from_signed_token,
    verify_signed_unsubscribe_token,
)
from app.services.verification_tokens import (
    create_signed_verification_token,
    verification_token_claims,
    verify_signed_verification_token,
)


LOGGER = logging.getLogger(__name__)
VERIFICATION_RESEND_INTERVAL = timedelta(minutes=1)
# Checked against when a token names no subscription, so a token that matches
# nothing takes the same checks as one that does.
_DUMMY_TOKEN_HASH = "0" * 64


class AlertSubscriptionError(Exception):
    """An operation refused. Each kind has its own HTTP answer."""


class AlertsSwitchedOff(AlertSubscriptionError):
    """This deployment sends no alerts, so they cannot be turned on."""


class AlertsNotEnabled(AlertSubscriptionError):
    """The investor has alerts off, so there is no address to verify."""


class VerificationRequestedRecently(AlertSubscriptionError):
    """A verification email went out less than a minute ago."""

    def __init__(self, retry_after_seconds: int):
        super().__init__(f"Verification can be requested again in {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class PreferencesChangedConcurrently(AlertSubscriptionError):
    """Another request changed the investor's subscription while this one ran."""


class VerificationEmailNotSent(AlertSubscriptionError):
    """The email sender did not accept the verification email.

    The request is marked failed. ``outcome`` says why the email did not go
    out.
    """

    def __init__(self, outcome: RecipientRejected | Unavailable | Misconfigured):
        super().__init__(type(outcome).__name__)
        self.outcome = outcome


class InvalidVerificationLink(AlertSubscriptionError):
    """The verification link is malformed, forged, expired or not the newest one."""


class SupersededVerificationLink(AlertSubscriptionError):
    """The request the link verifies changed while it was being verified."""


@dataclass(frozen=True)
class AlertPreferences:  # pylint: disable=too-many-instance-attributes
    """What an investor's alert settings show.

    ``feature_enabled`` is whether this deployment sends alerts at all.
    ``enabled`` needs both the subscription and its rule on. Before anything
    is saved, alerts are off with the default rule, at the account address.
    """

    feature_enabled: bool
    enabled: bool
    email: str
    min_confidence: float
    sentiment_labels: tuple[str, ...]
    verification_status: VerificationStatus
    verification_requested_at: datetime | None
    verified_at: datetime | None
    last_delivery_status: str | None
    last_delivery_error_code: str | None
    last_delivery_at: datetime | None


@dataclass(frozen=True)
class Saved:
    """What a save stored, and the raw unsubscribe token when it created one.

    The first save that turns alerts on creates the token. It is returned
    only then; the database keeps only its hash.
    """

    preferences: AlertPreferences
    unsubscribe_token: str | None


def read(db: Session, *, investor_id: UUID, account_email: str) -> AlertPreferences:
    """The investor's alert settings."""
    subscription, rule = _load(db, investor_id)
    return _preferences(subscription, rule, account_email=account_email)


def save(  # pylint: disable=too-many-arguments,too-many-locals
    db: Session,
    *,
    investor_id: UUID,
    account_email: str,
    enabled: bool,
    sentiment_labels: Sequence[str],
    min_confidence: float,
    sender: EmailSender,
) -> Saved:
    """Store the investor's alert rule, and send a verification link when one is due.

    With alerts on, a new or changed address gets a link at once, and an
    address still waiting for verification gets a new one at most once a
    minute. Raises ``AlertsSwitchedOff`` when turning alerts on while the
    deployment sends none, ``PreferencesChangedConcurrently`` when another
    request changed the subscription meanwhile, and
    ``VerificationEmailNotSent`` when the link was not sent.
    """
    if enabled and not settings.NOTIFICATIONS_ENABLED:
        raise AlertsSwitchedOff()
    now = datetime.now(timezone.utc)
    address = _comparable(account_email)
    existing = alert_subscription_crud.get_subscription_by_investor(db, investor_id)
    # Decided before the upsert, which refreshes ``existing`` in place.
    verification_due = enabled and _verification_due(existing, address, now)
    unsubscribe_token = None
    token_hash = cast(str | None, existing.unsubscribe_token_hash) if existing else None
    if enabled and not token_hash:
        unsubscribe_token = secrets.token_urlsafe(32)
        token_hash = _sha256(unsubscribe_token)

    try:
        subscription = alert_subscription_crud.upsert_subscription(
            db,
            investor_id=investor_id,
            email=address,
            enabled=enabled,
            unsubscribe_token_hash=token_hash,
            commit=False,
        )
        rule = alert_rule_crud.upsert_default_alert_rule(
            db,
            investor_id=investor_id,
            sentiment_labels=sentiment_labels,
            min_confidence=min_confidence,
            enabled=enabled,
            commit=False,
        )
        request = None
        # A verification made since ``existing`` was read leaves nothing to request.
        if verification_due and subscription.verification_status != VerificationStatus.VERIFIED:
            request = _reserve(db, subscription, now)
            if request is None:
                raise PreferencesChangedConcurrently()
        preferences = _preferences(subscription, rule, account_email=account_email)
        db.commit()
    except Exception:
        db.rollback()
        raise

    if request is None:
        return Saved(preferences, unsubscribe_token)
    _send_verification(db, request, sender)
    return Saved(_reloaded(db, investor_id, account_email), unsubscribe_token)


def request_verification(
    db: Session,
    *,
    investor_id: UUID,
    account_email: str,
    sender: EmailSender,
) -> AlertPreferences:
    """Send the investor a new verification link, at most once a minute.

    Sends nothing when the address is already verified. Raises
    ``AlertsSwitchedOff`` while the deployment sends no alerts,
    ``AlertsNotEnabled`` when the investor has alerts off,
    ``VerificationRequestedRecently`` within a minute of the last request,
    and ``VerificationEmailNotSent`` when the link was not sent.
    """
    if not settings.NOTIFICATIONS_ENABLED:
        raise AlertsSwitchedOff()
    subscription, rule = _load(db, investor_id)
    if subscription is None or not subscription.enabled:
        raise AlertsNotEnabled()
    if subscription.verification_status == VerificationStatus.VERIFIED:
        return _preferences(subscription, rule, account_email=account_email)

    now = datetime.now(timezone.utc)
    previous = cast(datetime | None, subscription.verification_requested_at)
    if previous is not None:
        wait = VERIFICATION_RESEND_INTERVAL - (now - _aware_utc(previous))
        if wait > timedelta(0):
            raise VerificationRequestedRecently(max(ceil(wait.total_seconds()), 1))
    try:
        request = _reserve(db, subscription, now)
        if request is None:
            # Another request was recorded first.
            raise VerificationRequestedRecently(
                int(VERIFICATION_RESEND_INTERVAL.total_seconds())
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    _send_verification(db, request, sender)
    return _reloaded(db, investor_id, account_email)


def confirm(db: Session, token: str) -> None:
    """Verify the address a verification link was sent to.

    Only the newest request's link works, for
    ``ALERT_VERIFICATION_TOKEN_TTL_HOURS`` after the request. Opening it again
    once the address is verified changes nothing. Raises
    ``InvalidVerificationLink`` for any other link, and
    ``SupersededVerificationLink`` when the request changed while it was being
    verified.
    """
    claims = verification_token_claims(token)
    if claims is None:
        raise InvalidVerificationLink()
    subscription_id, _requested_at = claims
    subscription = alert_subscription_crud.get_subscription(db, subscription_id)
    if (
        subscription is None
        or not subscription.unsubscribe_token_hash
        or subscription.verification_requested_at is None
    ):
        raise InvalidVerificationLink()

    now = datetime.now(timezone.utc)
    requested_at = cast(datetime, subscription.verification_requested_at)
    verified_id = verify_signed_verification_token(
        token,
        str(subscription.unsubscribe_token_hash),
        requested_at,
        now=now,
        ttl=timedelta(hours=settings.ALERT_VERIFICATION_TOKEN_TTL_HOURS),
    )
    if verified_id != subscription_id:
        raise InvalidVerificationLink()
    if subscription.verification_status == VerificationStatus.VERIFIED:
        return
    if subscription.verification_status != VerificationStatus.PENDING:
        raise InvalidVerificationLink()

    confirmed = alert_subscription_crud.confirm_verification(
        db,
        cast(UUID, subscription.investor_id),
        email=str(subscription.email),
        requested_at=requested_at,
        verified_at=now,
    )
    if confirmed is None:
        raise SupersededVerificationLink()


def unsubscribe(db: Session, token: str) -> None:
    """Turn alerts off for the subscription a raw or signed unsubscribe token belongs to."""
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

    candidate_hash = _sha256(token)
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
            cast(UUID, subscription.id),
            expected_unsubscribe_token_hash=stored_hash,
        )


@dataclass(frozen=True)
class _Request:
    """A recorded verification request, whose email is about to go out."""

    investor_id: UUID
    subscription_id: UUID
    email: str
    unsubscribe_token_hash: str
    requested_at: datetime


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    """Return one timestamp as an aware UTC value."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _comparable(email: str) -> str:
    """An address in the form saved addresses are compared in."""
    return str(email).strip().lower()


def _load(
    db: Session,
    investor_id: UUID,
) -> tuple[AlertSubscription | None, AlertRule | None]:
    """The two rows an investor's alert settings are stored in."""
    return (
        alert_subscription_crud.get_subscription_by_investor(db, investor_id),
        alert_rule_crud.get_default_alert_rule(db, investor_id),
    )


def _preferences(
    subscription: AlertSubscription | None,
    rule: AlertRule | None,
    *,
    account_email: str,
) -> AlertPreferences:
    """The settings the stored rows show, with defaults for any row not saved yet."""
    return AlertPreferences(
        feature_enabled=settings.NOTIFICATIONS_ENABLED,
        enabled=bool(
            subscription is not None
            and subscription.enabled
            and rule is not None
            and rule.enabled
        ),
        email=str(subscription.email) if subscription is not None else account_email,
        min_confidence=(
            float(rule.min_confidence)
            if rule is not None
            else settings.ALERT_DEFAULT_MIN_CONFIDENCE
        ),
        sentiment_labels=(
            tuple(str(label) for label in cast(list[str], rule.sentiment_labels))
            if rule is not None
            else DEFAULT_ALERT_SENTIMENT_LABELS
        ),
        verification_status=(
            VerificationStatus(str(subscription.verification_status))
            if subscription is not None
            else VerificationStatus.UNVERIFIED
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
    )


def _reloaded(db: Session, investor_id: UUID, account_email: str) -> AlertPreferences:
    """The settings as stored now, after a verification email went out."""
    subscription, rule = _load(db, investor_id)
    if subscription is None or rule is None:
        raise PreferencesChangedConcurrently()
    return _preferences(subscription, rule, account_email=account_email)


def _verification_due(
    existing: AlertSubscription | None,
    address: str,
    now: datetime,
) -> bool:
    """Whether turning alerts on for ``address`` should send a verification link now."""
    if existing is None or _comparable(str(existing.email)) != address:
        return True
    if existing.verification_status == VerificationStatus.VERIFIED:
        return False
    requested_at = cast(datetime | None, existing.verification_requested_at)
    return (
        requested_at is None
        or now - _aware_utc(requested_at) >= VERIFICATION_RESEND_INTERVAL
    )


def _reserve(db: Session, subscription: AlertSubscription, now: datetime) -> _Request | None:
    """Record a verification request in the open transaction.

    Returns None when another request changed the subscription first.
    """
    reserved = alert_subscription_crud.reserve_verification(
        db,
        cast(UUID, subscription.investor_id),
        observed=VerificationState.of(subscription),
        requested_at=now,
        commit=False,
    )
    if reserved is None:
        return None
    return _Request(
        investor_id=cast(UUID, reserved.investor_id),
        subscription_id=cast(UUID, reserved.id),
        email=str(reserved.email),
        unsubscribe_token_hash=str(reserved.unsubscribe_token_hash or ""),
        requested_at=now,
    )


def _send_verification(db: Session, request: _Request, sender: EmailSender) -> None:
    """Email the request's verification link, or mark the request failed and raise."""
    outcome = _verification_outcome(request, sender)
    if isinstance(outcome, Accepted):
        return
    LOGGER.error(
        "Verification email not sent outcome=%s error_code=%s",
        type(outcome).__name__,
        outcome.code,
    )
    alert_subscription_crud.fail_verification(
        db,
        request.investor_id,
        email=request.email,
        requested_at=request.requested_at,
    )
    raise VerificationEmailNotSent(outcome)


def _verification_outcome(request: _Request, sender: EmailSender) -> SendOutcome:
    """Write the verification email and hand it to ``sender``."""
    try:
        token = create_signed_verification_token(
            request.subscription_id,
            request.unsubscribe_token_hash,
            request.requested_at,
        )
        base_url = settings.FRONTEND_BASE_URL.strip().rstrip("/")
        verification_url = f"{base_url}/verify-notifications/?{urlencode({'t': token})}"
        subject, html, text = render_verification_email(verification_url)
    except ValueError:
        return Misconfigured("invalid_notification_configuration")
    return sender.send(
        OutgoingEmail(to=request.email, subject=subject, html=html, text=text)
    )
