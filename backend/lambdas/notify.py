"""SQS consumer for database-backed SES watchlist alerts.

Durable ledger outcomes deduplicate normal SQS replays. The external boundary
is still at least once: SES can accept a message immediately before the Lambda
loses its response or its outcome transaction. A stale takeover may then send
that message again. SES SendEmail has no idempotency key that can close this
distributed transaction gap without choosing possible message loss instead.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, NoReturn, cast
from urllib.parse import quote, urlencode
from uuid import UUID

from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
)
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from lambdas.common import (
    correlation_id,
    database_session,
    load_runtime_configuration,
    log_event,
    receive_attempt,
)

# Settings and database modules read environment values at import time. Resolve
# encrypted runtime values first, matching the API Lambda cold-start order.
load_runtime_configuration()

# pylint: disable=wrong-import-position,too-many-lines
from app.core.config import settings  # noqa: E402
from app.crud import alert_delivery as alert_delivery_crud  # noqa: E402
from app.crud import alert_rule as alert_rule_crud  # noqa: E402
from app.crud import alert_subscription as alert_subscription_crud  # noqa: E402
from app.crud import watchlist_ticker as watchlist_ticker_crud  # noqa: E402
from app.models.artifact import Artifact  # noqa: E402
from app.models.artifact_sentiment import ArtifactSentiment  # noqa: E402
from app.models.artifact_summary import ArtifactSummary  # noqa: E402
from app.models.ticker import Ticker  # noqa: E402
from app.services import ses_alerts  # noqa: E402
from app.services.alert_templates import (  # noqa: E402
    render_alert_email,
    render_rollup_email,
)
from app.services.unsubscribe_tokens import (  # noqa: E402
    create_signed_unsubscribe_token,
)


STAGE = "notify"
_CONFIDENCE_TOLERANCE = Decimal("0.0001")
_LIVE_SEND_INTERVAL_SECONDS = 1.0
_SEND_LOCK = threading.Lock()
_LAST_LIVE_SEND_AT: float | None = None


class PermanentNotificationError(ValueError):
    """A malformed or stale message that a retry cannot repair."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class RetryableNotificationError(RuntimeError):
    """A dependency or state race that SQS should retry."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class NotificationMessage(BaseModel):
    """Versioned producer contract for one analyzed artifact."""

    schema_version: Literal[1] = 1
    artifact_id: UUID
    ticker: str = Field(min_length=1, max_length=10, pattern=r"^[A-Z0-9.-]+$")
    scrape_run_id: UUID
    sentiment_label: Literal["positive", "negative"]
    confidence_score: Decimal = Field(ge=0, le=1)

    model_config = {"extra": "forbid"}

    @field_validator("ticker", mode="before")
    @classmethod
    def uppercase_ticker(cls, value: object) -> object:
        """Normalise the producer ticker before applying its pattern."""
        return value.strip().upper() if isinstance(value, str) else value


@dataclass(frozen=True)
class NotificationContext:  # pylint: disable=too-many-instance-attributes
    """Canonical database values used to match and render an alert."""

    message: NotificationMessage
    ticker_id: UUID
    ticker_symbol: str
    company_name: str
    artifact_title: str | None
    summary_text: str | None
    sentiment_label: str
    confidence_score: Decimal


@dataclass(frozen=True)
class RulePreferences:
    """Detached rule values needed during one delivery attempt."""

    id: UUID
    enabled: bool
    rule_type: str
    sentiment_labels: tuple[str, ...]
    min_confidence: Decimal


@dataclass(frozen=True)
class WatcherPreferences:  # pylint: disable=too-many-instance-attributes
    """Detached subscription and rule values for one investor."""

    investor_id: UUID
    subscription_id: UUID
    email: str
    enabled: bool
    verification_status: str
    verification_requested_at: datetime | None
    unsubscribe_token_hash: str | None
    rule: RulePreferences | None


@dataclass(frozen=True)
class DeliveryLease:
    """The values required to apply a guarded delivery transition."""

    id: UUID
    investor_id: UUID
    claimed_at: datetime
    rollup: bool


def parse_notification_record(record: dict[str, Any]) -> NotificationMessage:
    """Parse one SQS body without logging its potentially private content."""
    try:
        body = record["body"]
        if not isinstance(body, str):
            raise TypeError("SQS body must be a string")
        return NotificationMessage.model_validate_json(body)
    except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise PermanentNotificationError(
            "SQS body does not match notification schema version 1",
            code="invalid_notification_message",
        ) from exc


def _decimal(value: object, *, field: str) -> Decimal:
    """Return one finite canonical decimal value."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RetryableNotificationError(
            f"Canonical {field} is not numeric",
            code="canonical_analysis_invalid",
        ) from exc
    if not result.is_finite():
        raise RetryableNotificationError(
            f"Canonical {field} is not finite",
            code="canonical_analysis_invalid",
        )
    return result


def _load_context(message: NotificationMessage) -> NotificationContext:
    """Load canonical content and reject message identity mismatches."""
    with database_session() as db:
        row = db.execute(
            select(
                Artifact.scrape_run_id.label("scrape_run_id"),
                Artifact.analysis_status.label("analysis_status"),
                Artifact.title.label("artifact_title"),
                Ticker.id.label("ticker_id"),
                Ticker.symbol.label("ticker_symbol"),
                Ticker.company_name.label("company_name"),
                ArtifactSentiment.sentiment_label.label("sentiment_label"),
                ArtifactSentiment.confidence_score.label("confidence_score"),
                ArtifactSummary.summary_text.label("summary_text"),
            )
            .outerjoin(Ticker, Ticker.id == Artifact.ticker_id)
            .outerjoin(
                ArtifactSentiment,
                ArtifactSentiment.artifact_id == Artifact.id,
            )
            .outerjoin(
                ArtifactSummary,
                ArtifactSummary.artifact_id == Artifact.id,
            )
            .where(Artifact.id == message.artifact_id)
        ).mappings().one_or_none()

    if row is None:
        raise RetryableNotificationError(
            "Artifact is not visible yet",
            code="artifact_not_visible",
        )
    if row["analysis_status"] != "completed":
        raise RetryableNotificationError(
            "Artifact analysis is not complete yet",
            code="analysis_not_complete",
        )
    if (
        row["ticker_id"] is None
        or row["ticker_symbol"] is None
        or row["company_name"] is None
        or row["sentiment_label"] is None
        or row["confidence_score"] is None
    ):
        raise RetryableNotificationError(
            "Canonical alert data is not visible yet",
            code="canonical_analysis_not_visible",
        )

    canonical_symbol = str(row["ticker_symbol"]).strip().upper()
    canonical_label = str(row["sentiment_label"]).strip().lower()
    canonical_confidence = _decimal(
        row["confidence_score"],
        field="confidence_score",
    )
    if not Decimal("0") <= canonical_confidence <= Decimal("1"):
        raise RetryableNotificationError(
            "Canonical confidence is outside the supported range",
            code="canonical_analysis_invalid",
        )
    identity_mismatch = (
        row["scrape_run_id"] != message.scrape_run_id
        or canonical_symbol != message.ticker
        or canonical_label != message.sentiment_label
        or abs(canonical_confidence - message.confidence_score)
        > _CONFIDENCE_TOLERANCE
    )
    if identity_mismatch:
        raise PermanentNotificationError(
            "Notification identity does not match the canonical artifact",
            code="notification_identity_mismatch",
        )

    return NotificationContext(
        message=message,
        ticker_id=row["ticker_id"],
        ticker_symbol=canonical_symbol,
        company_name=str(row["company_name"]),
        artifact_title=row["artifact_title"],
        summary_text=row["summary_text"],
        sentiment_label=canonical_label,
        confidence_score=canonical_confidence,
    )


def _load_preferences(investor_id: UUID) -> WatcherPreferences | None:
    """Copy one investor's current preferences out of a short DB session."""
    with database_session() as db:
        subscription = alert_subscription_crud.get_subscription_by_investor(
            db,
            investor_id,
        )
        if subscription is None:
            return None
        rule = alert_rule_crud.get_default_alert_rule(db, investor_id)
        rule_snapshot = None
        if rule is not None:
            rule_snapshot = RulePreferences(
                id=cast(UUID, rule.id),
                enabled=bool(rule.enabled),
                rule_type=str(rule.rule_type),
                sentiment_labels=tuple(
                    str(item)
                    for item in cast(list[str], rule.sentiment_labels)
                ),
                min_confidence=_decimal(
                    rule.min_confidence,
                    field="minimum confidence",
                ),
            )
        return WatcherPreferences(
            investor_id=investor_id,
            subscription_id=cast(UUID, subscription.id),
            email=str(subscription.email),
            enabled=bool(subscription.enabled),
            verification_status=str(subscription.verification_status),
            verification_requested_at=cast(
                datetime | None,
                subscription.verification_requested_at,
            ),
            unsubscribe_token_hash=cast(
                str | None,
                subscription.unsubscribe_token_hash,
            ),
            rule=rule_snapshot,
        )


def _rule_matches(rule: object, label: str, confidence: Decimal) -> bool:
    """Apply the enabled label and inclusive confidence threshold gates."""
    if not bool(getattr(rule, "enabled", False)):
        return False
    if getattr(rule, "rule_type", "sentiment_threshold") != "sentiment_threshold":
        return False
    labels = {
        str(item).strip().lower()
        for item in (getattr(rule, "sentiment_labels", ()) or ())
    }
    try:
        threshold = Decimal(str(getattr(rule, "min_confidence")))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return label.lower() in labels and confidence >= threshold


def _preferences_match(
    preferences: WatcherPreferences | None,
    context: NotificationContext,
) -> bool:
    return bool(
        preferences is not None
        and preferences.enabled
        and preferences.rule is not None
        and _rule_matches(
            preferences.rule,
            context.sentiment_label,
            context.confidence_score,
        )
    )


def _lease(delivery: Any, *, rollup: bool) -> DeliveryLease:
    """Detach the exact lease values needed after the claim commit."""
    if delivery.claimed_at is None:
        raise RetryableNotificationError(
            "Claim did not return its lease timestamp",
            code="claim_state_invalid",
        )
    return DeliveryLease(
        id=delivery.id,
        investor_id=delivery.investor_id,
        claimed_at=delivery.claimed_at,
        rollup=rollup,
    )


def _claim_direct(
    context: NotificationContext,
    preferences: WatcherPreferences,
) -> tuple[DeliveryLease | None, str | None]:
    """Commit a direct claim, or return the existing terminal state."""
    with database_session() as db:
        delivery = alert_delivery_crud.claim(
            db,
            preferences.investor_id,
            context.message.artifact_id,
            context.message.scrape_run_id,
            preferences.rule.id if preferences.rule else None,
            stale_after_minutes=settings.ALERT_CLAIM_STALE_MINUTES,
        )
        if delivery is not None:
            return _lease(delivery, rollup=False), None
        existing = alert_delivery_crud.get_for_artifact(
            db,
            preferences.investor_id,
            context.message.artifact_id,
        )
        return None, str(existing.status) if existing is not None else None


def _claim_rollup(
    context: NotificationContext,
    preferences: WatcherPreferences,
) -> tuple[DeliveryLease | None, str | None]:
    """Commit the one allowed rollup claim for this investor and run."""
    with database_session() as db:
        delivery = alert_delivery_crud.claim_rollup(
            db,
            preferences.investor_id,
            context.message.scrape_run_id,
            preferences.rule.id if preferences.rule else None,
            stale_after_minutes=settings.ALERT_CLAIM_STALE_MINUTES,
        )
        if delivery is not None:
            return _lease(delivery, rollup=True), None
        existing = alert_delivery_crud.get_rollup(
            db,
            preferences.investor_id,
            context.message.scrape_run_id,
        )
        return None, str(existing.status) if existing is not None else None


def _transition_delivery(  # pylint: disable=too-many-arguments,too-many-branches
    lease: DeliveryLease,
    outcome: str,
    *,
    ses_message_id: str | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> str:
    """Commit a ledger transition and D17 subscription mirror atomically."""
    delivery_at = datetime.now(timezone.utc)
    with database_session() as db:
        if outcome == "sent":
            changed = alert_delivery_crud.mark_sent(
                db,
                lease.id,
                lease.claimed_at,
                ses_message_id or "",
                commit=False,
            )
        elif outcome == "rejected":
            changed = alert_delivery_crud.mark_rejected(
                db,
                lease.id,
                lease.claimed_at,
                error_code or "rejected",
                error_detail,
                commit=False,
            )
        elif outcome == "failed":
            changed = alert_delivery_crud.mark_failed(
                db,
                lease.id,
                lease.claimed_at,
                error_code or "retryable_failure",
                error_detail,
                commit=False,
            )
        elif outcome == "suppressed_cap":
            changed = alert_delivery_crud.mark_suppressed_cap(
                db,
                lease.id,
                lease.claimed_at,
                error_detail,
                commit=False,
            )
        elif outcome == "suppressed_budget":
            changed = alert_delivery_crud.mark_suppressed_budget(
                db,
                lease.id,
                lease.claimed_at,
                error_detail,
                commit=False,
            )
        else:
            raise ValueError(f"Unknown delivery outcome: {outcome}")

        if changed is None:
            raise RetryableNotificationError(
                "Delivery claim was replaced before its outcome commit",
                code="delivery_lease_lost",
            )
        subscription = alert_subscription_crud.record_delivery_outcome(
            db,
            investor_id=lease.investor_id,
            delivery_status=str(changed.status),
            delivery_at=delivery_at,
            error_code=error_code,
            commit=False,
        )
        if subscription is None:
            raise RetryableNotificationError(
                "Subscription disappeared before its outcome commit",
                code="subscription_state_changed",
            )
        db.commit()
        return str(changed.status)


def _reject_with_identity_correction(
    lease: DeliveryLease,
    preferences: WatcherPreferences,
    verification_status: str,
) -> None:
    """Correct SES state and reject the delivery in one transaction."""
    delivery_at = datetime.now(timezone.utc)
    with database_session() as db:
        correction_arguments: dict[str, Any] = {
            "investor_id": preferences.investor_id,
            "verification_status": verification_status,
            "expected_verification_status": preferences.verification_status,
            "expected_email": preferences.email,
            "expected_verification_requested_at": (
                preferences.verification_requested_at
            ),
            "commit": False,
        }
        if (
            verification_status == "pending"
            and preferences.verification_requested_at is not None
        ):
            correction_arguments["verification_requested_at"] = (
                preferences.verification_requested_at
            )
        corrected = alert_subscription_crud.update_verification_state(
            db,
            **correction_arguments,
        )
        changed = alert_delivery_crud.mark_rejected(
            db,
            lease.id,
            lease.claimed_at,
            "recipient_not_verified",
            "SES identity is not verified",
            commit=False,
        )
        if corrected is None or changed is None:
            raise RetryableNotificationError(
                "Preferences changed during the SES identity check",
                code="subscription_state_changed",
            )
        subscription = alert_subscription_crud.record_delivery_outcome(
            db,
            investor_id=lease.investor_id,
            delivery_status="rejected",
            delivery_at=delivery_at,
            error_code="recipient_not_verified",
            commit=False,
        )
        if subscription is None:
            raise RetryableNotificationError(
                "Subscription disappeared before rejection commit",
                code="subscription_state_changed",
            )
        db.commit()


def _fail_and_retry(lease: DeliveryLease, *, code: str) -> NoReturn:
    """Persist a sanitized retryable outcome, then fail the SQS record."""
    _transition_delivery(
        lease,
        "failed",
        error_code=code,
        error_detail="A temporary notification dependency failed",
    )
    raise RetryableNotificationError(
        "Notification dependency failed",
        code=code,
    )


def _check_identity(
    lease: DeliveryLease,
    preferences: WatcherPreferences,
) -> bool:
    """Require both local and live SES verification before sending."""
    if preferences.verification_status != "verified":
        _transition_delivery(
            lease,
            "rejected",
            error_code="recipient_not_verified",
            error_detail="Local subscription identity is not verified",
        )
        return False

    try:
        status = ses_alerts.identity_status(preferences.email)
    except ValueError:
        _transition_delivery(
            lease,
            "rejected",
            error_code="invalid_recipient",
            error_detail="Recipient address is invalid",
        )
        return False
    except (ClientError, BotoCoreError):
        _fail_and_retry(lease, code="ses_identity_check_failed")
    except Exception:  # pylint: disable=broad-exception-caught
        _fail_and_retry(lease, code="identity_check_failed")

    if status == "verified":
        return True
    if status == "temporary_failure":
        _fail_and_retry(lease, code="ses_identity_temporary_failure")
    if status not in {"unverified", "pending", "failed"}:
        _fail_and_retry(lease, code="ses_identity_state_invalid")
    _reject_with_identity_correction(lease, preferences, status)
    return False


def _notification_urls(
    context: NotificationContext,
    preferences: WatcherPreferences,
) -> tuple[str, str]:
    """Build app and signed unsubscribe URLs without exposing stored hashes."""
    if not preferences.unsubscribe_token_hash:
        raise RetryableNotificationError(
            "Enabled subscription lacks an unsubscribe signing key",
            code="unsubscribe_key_missing",
        )
    token = create_signed_unsubscribe_token(
        preferences.subscription_id,
        preferences.unsubscribe_token_hash,
    )
    base_url = settings.FRONTEND_BASE_URL.strip().rstrip("/")
    encoded_ticker = quote(context.ticker_symbol, safe="")
    news_url = f"{base_url}/ticker/{encoded_ticker}/news/"
    query = urlencode({"token": token})
    unsubscribe_url = f"{base_url}/unsubscribe/?{query}"
    return news_url, unsubscribe_url


def _send_alert(  # pylint: disable=too-many-arguments
    *,
    to: str,
    subject: str,
    html: str,
    text_body: str,
    unsubscribe_url: str,
) -> str:
    """Rate-limit live sends inside one fan-out Lambda invocation."""
    global _LAST_LIVE_SEND_AT  # pylint: disable=global-statement
    with _SEND_LOCK:
        if not settings.NOTIFICATIONS_DRY_RUN and _LAST_LIVE_SEND_AT is not None:
            delay = _LIVE_SEND_INTERVAL_SECONDS - (
                time.monotonic() - _LAST_LIVE_SEND_AT
            )
            if delay > 0:
                time.sleep(delay)
        try:
            return ses_alerts.send_alert(
                to=to,
                subject=subject,
                html=html,
                text=text_body,
                unsubscribe_url=unsubscribe_url,
            )
        finally:
            if not settings.NOTIFICATIONS_DRY_RUN:
                _LAST_LIVE_SEND_AT = time.monotonic()


def _send_rendered(
    lease: DeliveryLease,
    preferences: WatcherPreferences,
    rendered: tuple[str, str, str],
    unsubscribe_url: str,
) -> None:
    """Send one rendered message and classify SES failures."""
    subject, html, text_body = rendered
    try:
        message_id = _send_alert(
            to=preferences.email,
            subject=subject,
            html=html,
            text_body=text_body,
            unsubscribe_url=unsubscribe_url,
        )
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "ClientError")
        if code in {"MessageRejected", "MessageRejectedException"}:
            _transition_delivery(
                lease,
                "rejected",
                error_code=code,
                error_detail="SES rejected the recipient or message",
            )
            return
        _fail_and_retry(lease, code=code[:128])
    except BotoCoreError:
        _fail_and_retry(lease, code="ses_transport_error")
    except ValueError as exc:
        code = (
            "invalid_recipient"
            if "recipient" in str(exc).lower()
            else "invalid_notification_configuration"
        )
        if code == "invalid_recipient":
            _transition_delivery(
                lease,
                "rejected",
                error_code=code,
                error_detail="Recipient address is invalid",
            )
            return
        _fail_and_retry(lease, code=code)
    except Exception:  # pylint: disable=broad-exception-caught
        _fail_and_retry(lease, code="ses_send_failed")

    _transition_delivery(
        lease,
        "sent",
        ses_message_id=message_id,
    )


def _preferences_still_current(
    expected: WatcherPreferences,
    context: NotificationContext,
) -> bool:
    """Recheck consent and matching rule just before the send boundary."""
    current = _load_preferences(expected.investor_id)
    return current == expected and _preferences_match(current, context)


def _at_daily_budget() -> bool:
    with database_session() as db:
        return (
            alert_delivery_crud.count_budget_commitments_last_24h(db)
            > settings.ALERT_DAILY_BUDGET
        )


def _over_run_cap(context: NotificationContext, investor_id: UUID) -> bool:
    with database_session() as db:
        return (
            alert_delivery_crud.count_for_run(
                db,
                investor_id,
                context.message.scrape_run_id,
            )
            > settings.ALERT_MAX_PER_INVESTOR_PER_RUN
        )


def _suppressed_count(context: NotificationContext, investor_id: UUID) -> int:
    with database_session() as db:
        return alert_delivery_crud.count_suppressed_for_run(
            db,
            investor_id,
            context.message.scrape_run_id,
        )


def _ensure_rollup(  # pylint: disable=too-many-return-statements
    context: NotificationContext,
    preferences: WatcherPreferences,
    *,
    identity_checked: bool,
) -> None:
    """Claim or recover the one rollup allowed for this scrape run."""
    lease, existing_status = _claim_rollup(context, preferences)
    if lease is None:
        if existing_status in {
            "claimed",
            "rollup_sent",
            "rejected",
            "suppressed_budget",
        }:
            return
        raise RetryableNotificationError(
            "Rollup claim could not be acquired",
            code="rollup_claim_unavailable",
        )

    if not identity_checked and not _check_identity(lease, preferences):
        return
    if _at_daily_budget():
        _transition_delivery(
            lease,
            "suppressed_budget",
            error_code="daily_budget",
            error_detail="Account daily alert budget reached",
        )
        log_event(
            stage=STAGE,
            event="suppressed",
            level=logging.WARNING,
            investor_id=preferences.investor_id,
            scrape_run_id=context.message.scrape_run_id,
            reason="daily_budget",
            rollup=True,
        )
        return
    if not _preferences_still_current(preferences, context):
        _transition_delivery(
            lease,
            "rejected",
            error_code="preferences_changed",
            error_detail="Alert preferences changed before send",
        )
        return

    count = _suppressed_count(context, preferences.investor_id)
    if count < 1:
        _fail_and_retry(lease, code="rollup_count_not_visible")
    try:
        news_url, unsubscribe_url = _notification_urls(context, preferences)
        rendered = render_rollup_email(
            ticker_symbol=context.ticker_symbol,
            company_name=context.company_name,
            suppressed_count=count,
            news_url=news_url,
            unsubscribe_url=unsubscribe_url,
        )
    except RetryableNotificationError:
        _fail_and_retry(lease, code="unsubscribe_key_missing")
    except (TypeError, ValueError):
        _fail_and_retry(lease, code="invalid_notification_configuration")
    _send_rendered(lease, preferences, rendered, unsubscribe_url)


def _process_watcher(  # pylint: disable=too-many-return-statements
    context: NotificationContext,
    investor_id: UUID,
) -> None:
    """Process one investor and artifact under the delivery ledger."""
    preferences = _load_preferences(investor_id)
    if not _preferences_match(preferences, context):
        return
    if preferences is None:
        return

    lease, existing_status = _claim_direct(context, preferences)
    if lease is None:
        if existing_status == "suppressed_cap":
            _ensure_rollup(
                context,
                preferences,
                identity_checked=False,
            )
            return
        if existing_status in {
            "claimed",
            "sent",
            "rejected",
            "suppressed_budget",
        }:
            return
        raise RetryableNotificationError(
            "Direct delivery claim could not be acquired",
            code="delivery_claim_unavailable",
        )

    if not _check_identity(lease, preferences):
        return
    if _over_run_cap(context, investor_id):
        _transition_delivery(
            lease,
            "suppressed_cap",
            error_code="per_run_cap",
            error_detail="Investor per-run alert limit reached",
        )
        _ensure_rollup(
            context,
            preferences,
            identity_checked=True,
        )
        return
    if _at_daily_budget():
        _transition_delivery(
            lease,
            "suppressed_budget",
            error_code="daily_budget",
            error_detail="Account daily alert budget reached",
        )
        log_event(
            stage=STAGE,
            event="suppressed",
            level=logging.WARNING,
            investor_id=investor_id,
            artifact_id=context.message.artifact_id,
            reason="daily_budget",
            rollup=False,
        )
        return
    if not _preferences_still_current(preferences, context):
        _transition_delivery(
            lease,
            "rejected",
            error_code="preferences_changed",
            error_detail="Alert preferences changed before send",
        )
        return

    try:
        news_url, unsubscribe_url = _notification_urls(context, preferences)
        rendered = render_alert_email(
            ticker_symbol=context.ticker_symbol,
            company_name=context.company_name,
            artifact_title=context.artifact_title,
            summary_text=context.summary_text,
            sentiment_label=context.sentiment_label,
            confidence_score=context.confidence_score,
            news_url=news_url,
            unsubscribe_url=unsubscribe_url,
        )
    except RetryableNotificationError:
        _fail_and_retry(lease, code="unsubscribe_key_missing")
    except (TypeError, ValueError):
        _fail_and_retry(lease, code="invalid_notification_configuration")
    _send_rendered(lease, preferences, rendered, unsubscribe_url)


def _process_record(record: dict[str, Any]) -> None:
    """Fan one canonical artifact out to each distinct watching investor."""
    message = parse_notification_record(record)
    context = _load_context(message)
    with database_session() as db:
        investor_ids = watchlist_ticker_crud.investor_ids_watching(
            db,
            context.ticker_id,
        )

    retry_codes: list[str] = []
    for investor_id in investor_ids:
        try:
            _process_watcher(context, investor_id)
        except PermanentNotificationError as exc:
            log_event(
                stage=STAGE,
                event="investor_skipped",
                level=logging.WARNING,
                investor_id=investor_id,
                artifact_id=message.artifact_id,
                error_code=exc.code,
            )
        except RetryableNotificationError as exc:
            retry_codes.append(exc.code)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Isolate every investor so successful siblings still dedupe.
            retry_codes.append(type(exc).__name__)

    if retry_codes:
        raise RetryableNotificationError(
            "At least one investor delivery needs a retry",
            code=retry_codes[0],
        )


def handler(event: dict[str, Any], _context: Any) -> dict[str, list[dict[str, str]]]:
    """Return exact SQS partial failures while isolating every record."""
    load_runtime_configuration()
    if not settings.NOTIFICATIONS_ENABLED:
        return {"batchItemFailures": []}

    records = event.get("Records", [])
    if not isinstance(records, list):
        log_event(
            stage=STAGE,
            event="invalid_event",
            level=logging.ERROR,
            error_code="records_not_list",
        )
        return {"batchItemFailures": []}

    failures: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            log_event(
                stage=STAGE,
                event="record_discarded",
                level=logging.WARNING,
                error_code="invalid_sqs_record",
            )
            continue
        started_at = time.monotonic()
        message_id = correlation_id(record)
        attempt = receive_attempt(record)
        try:
            _process_record(record)
        except PermanentNotificationError as exc:
            log_event(
                stage=STAGE,
                event="record_discarded",
                started_at=started_at,
                level=logging.WARNING,
                correlation_id=message_id,
                attempt=attempt,
                error_code=exc.code,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # A raised record would make Lambda retry the entire SQS batch.
            error_code = getattr(exc, "code", type(exc).__name__)
            log_event(
                stage=STAGE,
                event="record_retry",
                started_at=started_at,
                level=logging.ERROR,
                correlation_id=message_id,
                attempt=attempt,
                error_code=error_code,
            )
            if message_id != "unknown":
                failures.append({"itemIdentifier": message_id})
        else:
            log_event(
                stage=STAGE,
                event="record_completed",
                started_at=started_at,
                correlation_id=message_id,
                attempt=attempt,
            )

    return {"batchItemFailures": failures}
