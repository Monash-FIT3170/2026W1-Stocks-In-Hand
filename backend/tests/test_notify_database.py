"""PostgreSQL integration coverage for the notification worker.

These tests commit for real, through the worker's own sessions, and remove
what they created afterwards.
"""

# pylint: disable=duplicate-code,redefined-outer-name,too-many-locals

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import Engine
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
    Accepted,
    OutgoingEmail,
    RecordingEmailSender,
    SendOutcome,
)
from lambdas import notify


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """The configured database, with alerts switched on for the worker."""
    database = create_engine(settings.DATABASE_URL)
    try:
        with database.connect() as connection:
            if not inspect(connection).has_table("alert_deliveries"):
                database.dispose()
                pytest.skip("Alert migrations are not applied")
    except OperationalError as exc:
        database.dispose()
        pytest.skip(f"PostgreSQL is unavailable: {exc}")
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ALERT_DAILY_BUDGET", 100_000, raising=False)
    monkeypatch.setattr(
        settings,
        "FRONTEND_BASE_URL",
        "https://app.example.test",
        raising=False,
    )
    try:
        yield database
    finally:
        database.dispose()


def _seed(engine: Engine, *, label: str) -> tuple[dict[str, uuid.UUID], dict[str, object]]:
    """Commit an artifact watched by one investor whose rule wants ``label``.

    Returns the ids ``_cleanup`` removes and the SQS record about the artifact.
    """
    suffix = uuid.uuid4().hex
    with Session(engine) as db:
        investor = Investor(
            email=f"notify-{suffix}@example.com",
            username="Notification integration test",
        )
        ticker = Ticker(
            symbol=f"T{suffix[:8].upper()}",
            company_name="Notification Test Limited",
            exchange="ASX",
        )
        platform = InformationPlatform(
            name=f"Notification test {suffix}",
            platform_type="test",
        )
        db.add_all([investor, ticker, platform])
        db.flush()

        scrape_run = ScrapeRun(
            platform_id=platform.id,
            ticker_id=ticker.id,
            status="completed",
            idempotency_key=f"notify:{suffix}",
        )
        watchlist = Watchlist(
            investor_id=investor.id,
            name="Notification test watchlist",
        )
        db.add_all([scrape_run, watchlist])
        db.flush()

        artifact = Artifact(
            scrape_run_id=scrape_run.id,
            ticker_id=ticker.id,
            artifact_type="announcement",
            title="Half year results",
            content_hash=f"notify-{suffix}",
            analysis_status="completed",
        )
        db.add(artifact)
        db.flush()
        db.add_all(
            [
                ArtifactSentiment(
                    artifact_id=artifact.id,
                    sentiment_label=label,
                    confidence_score=Decimal("0.8200"),
                ),
                ArtifactSummary(
                    artifact_id=artifact.id,
                    summary_text="Earnings were below expectations.",
                ),
                WatchlistTicker(
                    watchlist_id=watchlist.id,
                    ticker_id=ticker.id,
                ),
                AlertSubscription(
                    investor_id=investor.id,
                    email=investor.email,
                    enabled=True,
                    verification_status="verified",
                    verification_requested_at=datetime.now(timezone.utc),
                    verified_at=datetime.now(timezone.utc),
                    unsubscribe_token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
                ),
                AlertRule(
                    investor_id=investor.id,
                    ticker_id=None,
                    rule_type="sentiment_threshold",
                    sentiment_labels=[label],
                    min_confidence=Decimal("0.7500"),
                    enabled=True,
                ),
            ]
        )
        db.commit()
        ids = {
            "investor": investor.id,
            "ticker": ticker.id,
            "platform": platform.id,
            "run": scrape_run.id,
            "watchlist": watchlist.id,
            "artifact": artifact.id,
        }
        message = {
            "schema_version": 1,
            "artifact_id": str(artifact.id),
            "ticker": ticker.symbol,
            "scrape_run_id": str(scrape_run.id),
            "sentiment_label": label,
            "confidence_score": "0.8200",
        }
    record = {
        "messageId": f"notify-{suffix}",
        "body": json.dumps(message),
        "attributes": {"ApproximateReceiveCount": "1"},
    }
    return ids, record


def _cleanup(engine: Engine, *, ids: dict[str, uuid.UUID]) -> None:
    """Remove only records created by this test, in foreign-key order."""
    with Session(engine) as db:
        db.query(AlertDelivery).filter(
            AlertDelivery.investor_id == ids["investor"]
        ).delete(synchronize_session=False)
        db.query(AlertRule).filter(
            AlertRule.investor_id == ids["investor"]
        ).delete(synchronize_session=False)
        db.query(AlertSubscription).filter(
            AlertSubscription.investor_id == ids["investor"]
        ).delete(synchronize_session=False)
        db.query(WatchlistTicker).filter(
            WatchlistTicker.watchlist_id == ids["watchlist"]
        ).delete(synchronize_session=False)
        db.query(Watchlist).filter(Watchlist.id == ids["watchlist"]).delete(
            synchronize_session=False
        )
        db.query(ArtifactSentiment).filter(
            ArtifactSentiment.artifact_id == ids["artifact"]
        ).delete(synchronize_session=False)
        db.query(ArtifactSummary).filter(
            ArtifactSummary.artifact_id == ids["artifact"]
        ).delete(synchronize_session=False)
        db.query(Artifact).filter(Artifact.id == ids["artifact"]).delete(
            synchronize_session=False
        )
        db.query(ScrapeRun).filter(ScrapeRun.id == ids["run"]).delete(
            synchronize_session=False
        )
        db.query(InformationPlatform).filter(
            InformationPlatform.id == ids["platform"]
        ).delete(synchronize_session=False)
        db.query(Ticker).filter(Ticker.id == ids["ticker"]).delete(
            synchronize_session=False
        )
        db.query(Investor).filter(Investor.id == ids["investor"]).delete(
            synchronize_session=False
        )
        db.commit()


@pytest.mark.parametrize("label", ["negative", "neutral"])
def test_worker_sends_and_deduplicates_against_postgres(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    """A canonical artifact sends once, recorded on its ledger row and the subscription.

    Neutral runs the same path: a neutral-only rule must fire end to end.
    """
    ids, record = _seed(engine, label=label)
    try:
        sender = RecordingEmailSender()
        monkeypatch.setattr(email_sender, "configured_sender", lambda **_: sender)

        assert notify.handler({"Records": [record]}, None) == {
            "batchItemFailures": []
        }
        assert notify.handler({"Records": [record]}, None) == {
            "batchItemFailures": []
        }
        assert len(sender.sent) == 1

        with Session(engine) as db:
            deliveries = list(
                db.scalars(
                    select(AlertDelivery).where(
                        AlertDelivery.investor_id == ids["investor"]
                    )
                )
            )
            subscription = db.scalar(
                select(AlertSubscription).where(
                    AlertSubscription.investor_id == ids["investor"]
                )
            )
            assert len(deliveries) == 1
            assert deliveries[0].status == "sent"
            assert deliveries[0].provider_message_id == "recorded-1"
            assert subscription is not None
            assert subscription.last_delivery_status == "sent"
            assert subscription.last_delivery_error_code is None
        # The seeded summary row has only joined text, so the alert recovers it.
        assert "Earnings were below expectations." in sender.sent[0].text
    finally:
        _cleanup(engine, ids=ids)


def test_the_claim_is_committed_before_the_alert_is_sent(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another worker sees the claim while the email is going out.

    So a redelivery that runs during the send finds the claim and sends
    nothing, and the cap and budget counts include it.
    """
    ids, record = _seed(engine, label="negative")
    seen: list[str | None] = []

    def answer(_email: OutgoingEmail) -> SendOutcome:
        with engine.connect() as connection:
            seen.append(
                connection.scalar(
                    select(AlertDelivery.status).where(
                        AlertDelivery.investor_id == ids["investor"]
                    )
                )
            )
        return Accepted("recorded-1")

    try:
        monkeypatch.setattr(
            email_sender,
            "configured_sender",
            lambda **_: RecordingEmailSender(answer),
        )

        assert notify.handler({"Records": [record]}, None) == {
            "batchItemFailures": []
        }

        assert seen == ["claimed"]
    finally:
        _cleanup(engine, ids=ids)
