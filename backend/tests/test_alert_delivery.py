"""Alert delivery through the notify handler, on Postgres with a fake sender.

Each test drives ``notify.handler`` with SQS records about a fresh ticker,
scrape run and analysed artifact, watched by a fresh investor with a verified
alert subscription. Every database session the worker opens is a savepoint
inside one transaction that the test rolls back, and a RecordingEmailSender
stands in for Brevo.
"""

# pylint: disable=duplicate-code,redefined-outer-name

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alert_delivery import AlertDelivery
from app.models.alert_rule import AlertRule
from app.models.alert_subscription import AlertSubscription
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.models.information_platform import InformationPlatform
from app.models.investor import Investor
from app.models.scrape_run import ScrapeRun
from app.models.ticker import Ticker
from app.models.watchlist import Watchlist
from app.models.watchlist_ticker import WatchlistTicker
from app.services import email_sender
from app.services.email_sender import (
    EmailSender,
    Misconfigured,
    RecipientRejected,
    RecordingEmailSender,
    Unavailable,
)
from lambdas import notify

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class WatchedArtifact:
    """An analysed artifact, the investor watching its ticker, and its SQS record."""

    investor_id: uuid.UUID
    email: str
    record: dict[str, object]

    @property
    def retry(self) -> dict[str, list[dict[str, object]]]:
        return {"batchItemFailures": [{"itemIdentifier": self.record["messageId"]}]}


NO_RETRY: dict[str, list] = {"batchItemFailures": []}


@pytest.fixture()
def session(monkeypatch: pytest.MonkeyPatch) -> Iterator[SessionFactory]:
    """Savepoint sessions for the worker, rolled back when the test ends."""
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as probe:
            if not inspect(probe).has_table("alert_deliveries"):
                engine.dispose()
                pytest.skip("Alert migrations are not applied")
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL is unavailable: {exc}")
    connection = engine.connect()
    outer = connection.begin()

    @contextmanager
    def savepoint_session() -> Iterator[Session]:
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(notify, "database_session", savepoint_session)
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_DAILY_BUDGET", 100_000, raising=False)
    monkeypatch.setattr(
        settings,
        "FRONTEND_BASE_URL",
        "https://app.example.test",
        raising=False,
    )
    try:
        yield savepoint_session
    finally:
        outer.rollback()
        connection.close()
        engine.dispose()


def _send_with(monkeypatch: pytest.MonkeyPatch, sender: EmailSender) -> None:
    monkeypatch.setattr(email_sender, "configured_sender", lambda **_: sender)


def _watched_artifact(session: SessionFactory) -> WatchedArtifact:
    """A negative artifact at 0.82 for an investor whose rule wants negative at 0.75."""
    suffix = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    with session() as db:
        investor = Investor(
            email=f"alert-delivery-{suffix}@example.com",
            username="Alert delivery test",
        )
        ticker = Ticker(
            symbol=f"T{suffix[:8].upper()}",
            company_name="Alert Delivery Test Limited",
            exchange="ASX",
        )
        platform = InformationPlatform(
            name=f"Alert delivery test {suffix}",
            platform_type="test",
        )
        db.add_all([investor, ticker, platform])
        db.flush()
        scrape_run = ScrapeRun(
            platform_id=platform.id,
            ticker_id=ticker.id,
            status="completed",
            idempotency_key=f"alert-delivery:{suffix}",
        )
        watchlist = Watchlist(investor_id=investor.id, name="Alert delivery test")
        db.add_all([scrape_run, watchlist])
        db.flush()
        artifact = Artifact(
            scrape_run_id=scrape_run.id,
            ticker_id=ticker.id,
            artifact_type="announcement",
            title="Half year results",
            content_hash=f"alert-delivery-{suffix}",
            analysis_status="completed",
        )
        db.add(artifact)
        db.flush()
        db.add_all(
            [
                ArtifactSentiment(
                    artifact_id=artifact.id,
                    sentiment_label="negative",
                    confidence_score=Decimal("0.8200"),
                ),
                ArtifactSummary(
                    artifact_id=artifact.id,
                    summary_text="Earnings were below expectations.",
                ),
                WatchlistTicker(watchlist_id=watchlist.id, ticker_id=ticker.id),
                AlertSubscription(
                    investor_id=investor.id,
                    email=investor.email,
                    enabled=True,
                    verification_status="verified",
                    verification_requested_at=now,
                    verified_at=now,
                    unsubscribe_token_hash="a" * 64,
                ),
                AlertRule(
                    investor_id=investor.id,
                    ticker_id=None,
                    rule_type="sentiment_threshold",
                    sentiment_labels=["negative"],
                    min_confidence=Decimal("0.7500"),
                    enabled=True,
                ),
            ]
        )
        watched = WatchedArtifact(
            investor_id=investor.id,
            email=investor.email,
            record={
                "messageId": f"alert-delivery-{suffix}",
                "body": json.dumps(
                    {
                        "schema_version": 1,
                        "artifact_id": str(artifact.id),
                        "ticker": ticker.symbol,
                        "scrape_run_id": str(scrape_run.id),
                        "sentiment_label": "negative",
                        "confidence_score": "0.8200",
                    }
                ),
                "attributes": {"ApproximateReceiveCount": "1"},
            },
        )
        db.commit()
    return watched


def _deliver(watched: WatchedArtifact) -> dict[str, list]:
    return notify.handler({"Records": [watched.record]}, None)


def _delivery(session: SessionFactory, watched: WatchedArtifact) -> AlertDelivery:
    with session() as db:
        return db.scalars(
            select(AlertDelivery).where(AlertDelivery.investor_id == watched.investor_id)
        ).one()


def _subscription(session: SessionFactory, watched: WatchedArtifact) -> AlertSubscription:
    with session() as db:
        return db.scalars(
            select(AlertSubscription).where(
                AlertSubscription.investor_id == watched.investor_id
            )
        ).one()


def test_an_accepted_alert_is_recorded_as_sent(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watched = _watched_artifact(session)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY

    assert [email.to for email in sender.sent] == [watched.email]
    assert sender.sent[0].unsubscribe_url is not None
    delivery = _delivery(session, watched)
    assert (delivery.status, delivery.provider_message_id) == ("sent", "recorded-1")
    subscription = _subscription(session, watched)
    assert subscription.last_delivery_status == "sent"
    assert subscription.last_delivery_error_code is None


@pytest.mark.parametrize(
    ("outcome", "status", "retried"),
    [
        (RecipientRejected("invalid_parameter"), "rejected", False),
        (Unavailable("rate_limit"), "failed", True),
        (Misconfigured("brevo_configuration_error"), "failed", True),
    ],
)
def test_an_unsent_alert_is_recorded_and_retried_only_when_a_retry_can_help(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    outcome: RecipientRejected | Unavailable | Misconfigured,
    status: str,
    retried: bool,
) -> None:
    watched = _watched_artifact(session)
    _send_with(monkeypatch, RecordingEmailSender([outcome]))

    assert _deliver(watched) == (watched.retry if retried else NO_RETRY)

    delivery = _delivery(session, watched)
    assert (delivery.status, delivery.error_code) == (status, outcome.code)
    subscription = _subscription(session, watched)
    assert (
        subscription.last_delivery_status,
        subscription.last_delivery_error_code,
    ) == (status, outcome.code)


def test_a_record_retried_after_a_temporary_refusal_sends_one_alert(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watched = _watched_artifact(session)
    _send_with(monkeypatch, RecordingEmailSender([Unavailable("rate_limit")]))
    assert _deliver(watched) == watched.retry

    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY
    assert len(sender.sent) == 1
    assert _delivery(session, watched).status == "sent"


def test_a_dry_run_records_the_alert_as_sent_with_a_dry_run_id(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", True, raising=False)
    watched = _watched_artifact(session)

    assert _deliver(watched) == NO_RETRY

    delivery = _delivery(session, watched)
    assert delivery.status == "sent"
    assert delivery.provider_message_id.startswith("dry-run-")
