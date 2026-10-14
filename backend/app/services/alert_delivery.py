"""Alert delivery: what an analysed artifact becomes for each watching investor.

``deliver_alerts`` takes one notification message. For every investor
watching the artifact's ticker it decides whether the artifact becomes an
alert, joins the scrape run's rollup or is held back, sends what it decided
through the email sender, and records the outcome in the delivery ledger.

An investor gets at most ``ALERT_MAX_PER_INVESTOR_PER_RUN`` alerts for one
scrape run. Each further match is suppressed, and the first one sends the
run's single rollup instead. Once ``ALERT_DAILY_BUDGET`` alerts went out or
were claimed in the last 24 hours, across every investor, further alerts are
suppressed for good, with no retry.

A record delivered again finds its ledger rows and sends nothing more. The
email boundary is still at least once: the provider can accept an email just
before the worker loses its answer or the transaction that records it, and a
claim taken over once it is stale may then send that email again.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from urllib.parse import quote, urlencode
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alert_vocabulary import DeliveryKind
from app.core.config import settings
from app.crud import alert_delivery as alert_delivery_crud
from app.crud import alert_rule as alert_rule_crud
from app.crud import alert_subscription as alert_subscription_crud
from app.crud import watchlist_ticker as watchlist_ticker_crud
from app.messages import NotificationMessage
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.ticker import Ticker
from app.services.alert_templates import render_alert_email, render_rollup_email
from app.services.artifact_summary import alert_text
from app.services.email_sender import (
    Accepted,
    EmailSender,
    OutgoingEmail,
    RecipientRejected,
)
from app.services.unsubscribe_tokens import create_signed_unsubscribe_token
from app.status import AnalysisStatus


SessionFactory = Callable[[], AbstractContextManager[Session]]

_CONFIDENCE_TOLERANCE = Decimal("0.0001")
_TEMPORARY_FAILURE = "A temporary notification dependency failed"
# A claim held in one of these statuses needs nothing more from this attempt:
# the email went out, will never go out, or another attempt holds a fresh
# claim on it.
_SETTLED = frozenset({"claimed", "sent", "rollup_sent", "rejected", "suppressed_budget"})
_CLAIM_UNAVAILABLE = {
    DeliveryKind.DIRECT: "delivery_claim_unavailable",
    DeliveryKind.ROLLUP: "rollup_claim_unavailable",
}


class AlertNotReady(RuntimeError):
    """The artifact or its analysis is not visible yet, so a retry may find it."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class AlertMismatch(ValueError):
    """The message disagrees with the stored artifact. A retry cannot fix it."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class _Retry(RuntimeError):
    """A state race in one investor's delivery that SQS should retry."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WatcherResult:
    """What one alert came to for one investor watching its ticker.

    ``kind`` is the delivery last attempted, and None when the investor's rule
    did not want the alert or the attempt failed before it began.
    ``recorded`` is the ledger status the attempt wrote, and None when it wrote
    none, as when an earlier attempt had already settled the delivery.
    ``retry_code`` is set when SQS should deliver the record again.
    """

    investor_id: UUID
    kind: DeliveryKind | None = None
    recorded: str | None = None
    retry_code: str | None = None


def deliver_alerts(
    message: NotificationMessage,
    *,
    sender: EmailSender,
    open_session: SessionFactory,
) -> list[WatcherResult]:
    """Deliver the alert about the message's artifact to every investor watching it.

    Raises ``AlertNotReady`` while the artifact or its analysis is not visible,
    and ``AlertMismatch`` when the message disagrees with the stored artifact.
    Each investor's delivery stands alone: a failure becomes that investor's
    ``retry_code``, and the others still get their alerts. ``open_session``
    opens one short database session; this module commits what it writes.
    """
    alert = _load_alert(message, open_session)
    with open_session() as db:
        investor_ids = watchlist_ticker_crud.investor_ids_watching(db, alert.ticker_id)
    return [
        _deliver_to(investor_id, alert, sender=sender, open_session=open_session)
        for investor_id in investor_ids
    ]


@dataclass(frozen=True)
class _Alert:  # pylint: disable=too-many-instance-attributes
    """The stored facts an alert about one artifact is matched on and written from."""

    message: NotificationMessage
    ticker_id: UUID
    ticker_symbol: str
    company_name: str
    artifact_title: str | None
    summary_text: str | None
    sentiment_label: str
    confidence_score: Decimal


@dataclass(frozen=True)
class _Rule:
    """An investor's alert rule, as read for one delivery."""

    id: UUID
    enabled: bool
    sentiment_labels: tuple[str, ...]
    min_confidence: Decimal


@dataclass(frozen=True)
class _Watcher:  # pylint: disable=too-many-instance-attributes
    """An investor's alert subscription and rule, as read for one delivery.

    Delivery reads it again just before sending and holds the alert back if
    anything here changed. It leaves out the subscription's last-delivery
    fields, which every delivery writes, so two deliveries to one investor at
    the same time do not see each other as a change.
    """

    investor_id: UUID
    subscription_id: UUID
    email: str
    enabled: bool
    verification_status: str
    verification_requested_at: datetime | None
    unsubscribe_token_hash: str | None
    rule: _Rule | None

    def wants(self, alert: _Alert) -> bool:
        """Whether alerts are on and the rule matches the label and confidence."""
        rule = self.rule
        if not self.enabled or rule is None or not rule.enabled:
            return False
        labels = {label.strip().lower() for label in rule.sentiment_labels}
        return alert.sentiment_label in labels and alert.confidence_score >= rule.min_confidence


@dataclass(frozen=True)
class _Lease:
    """The values a guarded ledger transition needs after the claim commit."""

    id: UUID
    investor_id: UUID
    claimed_at: datetime
    kind: DeliveryKind


def _decimal(value: object, *, field: str) -> Decimal:
    """Return one finite canonical decimal value."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AlertNotReady(
            f"Canonical {field} is not numeric",
            code="canonical_analysis_invalid",
        ) from exc
    if not result.is_finite():
        raise AlertNotReady(
            f"Canonical {field} is not finite",
            code="canonical_analysis_invalid",
        )
    return result


def _load_alert(message: NotificationMessage, open_session: SessionFactory) -> _Alert:
    """Load canonical content and reject message identity mismatches."""
    with open_session() as db:
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
            )
            .outerjoin(Ticker, Ticker.id == Artifact.ticker_id)
            .outerjoin(
                ArtifactSentiment,
                ArtifactSentiment.artifact_id == Artifact.id,
            )
            .where(Artifact.id == message.artifact_id)
        ).mappings().one_or_none()
        summary_text = alert_text(db, message.artifact_id)

    if row is None:
        raise AlertNotReady(
            "Artifact is not visible yet",
            code="artifact_not_visible",
        )
    if row["analysis_status"] != AnalysisStatus.COMPLETED:
        raise AlertNotReady(
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
        raise AlertNotReady(
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
        raise AlertNotReady(
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
        raise AlertMismatch(
            "Notification identity does not match the canonical artifact",
            code="notification_identity_mismatch",
        )

    return _Alert(
        message=message,
        ticker_id=row["ticker_id"],
        ticker_symbol=canonical_symbol,
        company_name=str(row["company_name"]),
        artifact_title=row["artifact_title"],
        summary_text=summary_text,
        sentiment_label=canonical_label,
        confidence_score=canonical_confidence,
    )


def _load_watcher(db: Session, investor_id: UUID) -> _Watcher | None:
    """Copy one investor's subscription and rule, or None without a subscription."""
    subscription = alert_subscription_crud.get_subscription_by_investor(db, investor_id)
    if subscription is None:
        return None
    rule = alert_rule_crud.get_default_alert_rule(db, investor_id)
    return _Watcher(
        investor_id=investor_id,
        subscription_id=cast(UUID, subscription.id),
        email=str(subscription.email),
        enabled=bool(subscription.enabled),
        verification_status=str(subscription.verification_status),
        verification_requested_at=cast(
            datetime | None,
            subscription.verification_requested_at,
        ),
        unsubscribe_token_hash=cast(str | None, subscription.unsubscribe_token_hash),
        rule=None if rule is None else _Rule(
            id=cast(UUID, rule.id),
            enabled=bool(rule.enabled),
            sentiment_labels=tuple(
                str(label) for label in cast(list[str], rule.sentiment_labels)
            ),
            min_confidence=_decimal(rule.min_confidence, field="minimum confidence"),
        ),
    )


def _links(alert: _Alert, subscription_id: UUID, unsubscribe_token_hash: str) -> tuple[str, str]:
    """The ticker's news page and a signed unsubscribe link without the stored hash."""
    token = create_signed_unsubscribe_token(subscription_id, unsubscribe_token_hash)
    base_url = settings.FRONTEND_BASE_URL.strip().rstrip("/")
    encoded_ticker = quote(alert.ticker_symbol, safe="")
    news_url = f"{base_url}/ticker/{encoded_ticker}/news/"
    query = urlencode({"t": token})
    unsubscribe_url = f"{base_url}/unsubscribe/?{query}"
    return news_url, unsubscribe_url


def _deliver_to(
    investor_id: UUID,
    alert: _Alert,
    *,
    sender: EmailSender,
    open_session: SessionFactory,
) -> WatcherResult:
    """Deliver the alert to one investor, turning any failure into a retry."""
    try:
        with open_session() as db:
            watcher = _load_watcher(db, investor_id)
        if watcher is None or not watcher.wants(alert):
            return WatcherResult(investor_id)
        return _Delivery(alert, watcher, sender, open_session).attempt(DeliveryKind.DIRECT)
    except (AlertNotReady, _Retry) as exc:
        return WatcherResult(investor_id, retry_code=exc.code)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Isolate every investor so successful siblings still dedupe.
        return WatcherResult(investor_id, retry_code=type(exc).__name__)


@dataclass(frozen=True)
class _Delivery:
    """One alert on its way to one investor whose rule wants it."""

    alert: _Alert
    watcher: _Watcher
    sender: EmailSender
    open_session: SessionFactory

    def attempt(self, kind: DeliveryKind) -> WatcherResult:
        """Claim, check, send and record a direct alert or the run's rollup.

        A direct alert past the per-run cap is suppressed, and the investor
        gets the run's rollup instead.
        """
        # Claim first, and commit the claim on its own. Every count below then
        # includes this claim and the claims other workers have committed, so
        # workers running at the same time cannot together overshoot the
        # per-run cap or the daily budget.
        lease, held = self._claim(kind)
        if lease is None:
            if kind is DeliveryKind.DIRECT and held == "suppressed_cap":
                # An earlier attempt passed the cap and may not have sent the
                # rollup.
                return self.attempt(DeliveryKind.ROLLUP)
            retry_code = None if held in _SETTLED else _CLAIM_UNAVAILABLE[kind]
            return WatcherResult(self.watcher.investor_id, kind, retry_code=retry_code)
        held_back = self._hold_back(lease)
        if held_back is not None:
            if held_back.recorded == "suppressed_cap":
                return self.attempt(DeliveryKind.ROLLUP)
            return held_back
        email = self._compose(lease)
        if isinstance(email, WatcherResult):
            return email
        return self._send(lease, email)

    def _claim(self, kind: DeliveryKind) -> tuple[_Lease | None, str | None]:
        """Commit a claim, or return the status of the row that already holds it."""
        investor_id = self.watcher.investor_id
        message = self.alert.message
        rule_id = self.watcher.rule.id if self.watcher.rule else None
        with self.open_session() as db:
            if kind is DeliveryKind.DIRECT:
                delivery = alert_delivery_crud.claim(
                    db,
                    investor_id,
                    message.artifact_id,
                    message.scrape_run_id,
                    rule_id,
                    stale_after_minutes=settings.ALERT_CLAIM_STALE_MINUTES,
                )
            else:
                delivery = alert_delivery_crud.claim_rollup(
                    db,
                    investor_id,
                    message.scrape_run_id,
                    rule_id,
                    stale_after_minutes=settings.ALERT_CLAIM_STALE_MINUTES,
                )
            if delivery is not None:
                return _lease(delivery, kind), None
            if kind is DeliveryKind.DIRECT:
                existing = alert_delivery_crud.get_for_artifact(
                    db,
                    investor_id,
                    message.artifact_id,
                )
            else:
                existing = alert_delivery_crud.get_rollup(
                    db,
                    investor_id,
                    message.scrape_run_id,
                )
            return None, str(existing.status) if existing is not None else None

    def _hold_back(self, lease: _Lease) -> WatcherResult | None:
        """Record why the alert stops before it is sent, or return None to send it."""
        if self.watcher.verification_status != "verified":
            return self._record(
                lease,
                "rejected",
                code="recipient_not_verified",
                detail="The subscription email has not been confirmed",
            )
        if lease.kind is DeliveryKind.DIRECT and self._over_run_cap():
            return self._record(
                lease,
                "suppressed_cap",
                code="per_run_cap",
                detail="Investor per-run alert limit reached",
            )
        if self._over_daily_budget():
            return self._record(
                lease,
                "suppressed_budget",
                code="daily_budget",
                detail="Account daily alert budget reached",
            )
        if not self._still_wanted():
            return self._record(
                lease,
                "rejected",
                code="preferences_changed",
                detail="Alert preferences changed before send",
            )
        return None

    def _over_run_cap(self) -> bool:
        with self.open_session() as db:
            return (
                alert_delivery_crud.count_for_run(
                    db,
                    self.watcher.investor_id,
                    self.alert.message.scrape_run_id,
                )
                > settings.ALERT_MAX_PER_INVESTOR_PER_RUN
            )

    def _over_daily_budget(self) -> bool:
        with self.open_session() as db:
            return (
                alert_delivery_crud.count_budget_commitments_last_24h(db)
                > settings.ALERT_DAILY_BUDGET
            )

    def _still_wanted(self) -> bool:
        """Whether the subscription and rule are unchanged since the claim's read."""
        with self.open_session() as db:
            current = _load_watcher(db, self.watcher.investor_id)
        return current is not None and current == self.watcher and current.wants(self.alert)

    def _compose(self, lease: _Lease) -> OutgoingEmail | WatcherResult:
        """The email to send, or the recorded failure when it cannot be written now."""
        capped = 0
        if lease.kind is DeliveryKind.ROLLUP:
            with self.open_session() as db:
                capped = alert_delivery_crud.count_suppressed_for_run(
                    db,
                    self.watcher.investor_id,
                    self.alert.message.scrape_run_id,
                )
            if capped < 1:
                return self._fail(lease, "rollup_count_not_visible")
        token_hash = self.watcher.unsubscribe_token_hash
        if not token_hash:
            return self._fail(lease, "unsubscribe_key_missing")
        alert = self.alert
        try:
            news_url, unsubscribe_url = _links(alert, self.watcher.subscription_id, token_hash)
            if lease.kind is DeliveryKind.DIRECT:
                subject, html, text = render_alert_email(
                    ticker_symbol=alert.ticker_symbol,
                    company_name=alert.company_name,
                    artifact_title=alert.artifact_title,
                    summary_text=alert.summary_text,
                    sentiment_label=alert.sentiment_label,
                    confidence_score=alert.confidence_score,
                    news_url=news_url,
                    unsubscribe_url=unsubscribe_url,
                )
            else:
                subject, html, text = render_rollup_email(
                    ticker_symbol=alert.ticker_symbol,
                    company_name=alert.company_name,
                    suppressed_count=capped,
                    news_url=news_url,
                    unsubscribe_url=unsubscribe_url,
                )
        except (TypeError, ValueError):
            return self._fail(lease, "invalid_notification_configuration")
        return OutgoingEmail(
            to=self.watcher.email,
            subject=subject,
            html=html,
            text=text,
            unsubscribe_url=unsubscribe_url,
        )

    def _send(self, lease: _Lease, email: OutgoingEmail) -> WatcherResult:
        """Send the email and record the sender's outcome.

        A refused recipient is final. Any other unsent outcome releases the
        claim as failed and retries the record.
        """
        # EmailSender is a Protocol, so pylint sees no return statement.
        outcome = self.sender.send(email)  # pylint: disable=assignment-from-no-return
        if isinstance(outcome, Accepted):
            return self._record(lease, "sent", provider_message_id=outcome.message_id)
        if isinstance(outcome, RecipientRejected):
            return self._record(lease, "rejected", code=outcome.code, detail=outcome.detail)
        return self._fail(lease, outcome.code)

    def _fail(self, lease: _Lease, code: str) -> WatcherResult:
        """Record a failure a retry may get past, and ask SQS for that retry."""
        return self._record(lease, "failed", code=code, detail=_TEMPORARY_FAILURE)

    def _record(  # pylint: disable=too-many-arguments
        self,
        lease: _Lease,
        outcome: str,
        *,
        code: str | None = None,
        detail: str | None = None,
        provider_message_id: str | None = None,
    ) -> WatcherResult:
        """Commit a ledger transition and the subscription's mirror of it together."""
        delivery_at = datetime.now(timezone.utc)
        with self.open_session() as db:
            if outcome == "sent":
                changed = alert_delivery_crud.mark_sent(
                    db,
                    lease.id,
                    lease.claimed_at,
                    provider_message_id or "",
                    commit=False,
                )
            elif outcome == "rejected":
                changed = alert_delivery_crud.mark_rejected(
                    db,
                    lease.id,
                    lease.claimed_at,
                    code or "rejected",
                    detail,
                    commit=False,
                )
            elif outcome == "failed":
                changed = alert_delivery_crud.mark_failed(
                    db,
                    lease.id,
                    lease.claimed_at,
                    code or "retryable_failure",
                    detail,
                    commit=False,
                )
            elif outcome == "suppressed_cap":
                changed = alert_delivery_crud.mark_suppressed_cap(
                    db,
                    lease.id,
                    lease.claimed_at,
                    detail,
                    commit=False,
                )
            elif outcome == "suppressed_budget":
                changed = alert_delivery_crud.mark_suppressed_budget(
                    db,
                    lease.id,
                    lease.claimed_at,
                    detail,
                    commit=False,
                )
            else:
                raise ValueError(f"Unknown delivery outcome: {outcome}")

            if changed is None:
                raise _Retry(
                    "Delivery claim was replaced before its outcome commit",
                    code="delivery_lease_lost",
                )
            subscription = alert_subscription_crud.record_delivery_outcome(
                db,
                investor_id=lease.investor_id,
                delivery_status=str(changed.status),
                delivery_at=delivery_at,
                error_code=code,
                commit=False,
            )
            if subscription is None:
                raise _Retry(
                    "Subscription disappeared before its outcome commit",
                    code="subscription_state_changed",
                )
            db.commit()
            recorded = str(changed.status)
        return WatcherResult(
            lease.investor_id,
            lease.kind,
            recorded=recorded,
            retry_code=code if recorded == "failed" else None,
        )


def _lease(delivery: Any, kind: DeliveryKind) -> _Lease:
    """Detach the exact lease values needed after the claim commit."""
    if delivery.claimed_at is None:
        raise _Retry(
            "Claim did not return its lease timestamp",
            code="claim_state_invalid",
        )
    return _Lease(
        id=delivery.id,
        investor_id=delivery.investor_id,
        claimed_at=delivery.claimed_at,
        kind=kind,
    )
