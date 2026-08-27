"""PostgreSQL integration coverage for the notification worker."""

# pylint: disable=duplicate-code,too-many-locals

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

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
from lambdas import notify


def _engine_or_skip():
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("alert_deliveries"):
                pytest.skip("Alert migrations are not applied")
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL is unavailable: {exc}")
    return engine


def _cleanup(engine, *, ids: dict[str, uuid.UUID]) -> None:
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


def test_worker_sends_and_deduplicates_against_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canonical artifact should send once and persist both D17 outcomes."""
    engine = _engine_or_skip()
    suffix = uuid.uuid4().hex
    ids: dict[str, uuid.UUID] = {}
    try:
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
                        sentiment_label="negative",
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
                "sentiment_label": "negative",
                "confidence_score": "0.8200",
            }

        send = Mock(return_value="ses-integration-message")
        monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", True, raising=False)
        monkeypatch.setattr(settings, "ALERT_DAILY_BUDGET", 100_000, raising=False)
        monkeypatch.setattr(
            settings,
            "FRONTEND_BASE_URL",
            "https://app.example.test",
            raising=False,
        )
        monkeypatch.setattr(
            notify.ses_alerts,
            "identity_status",
            lambda _email: "verified",
        )
        monkeypatch.setattr(notify.ses_alerts, "send_alert", send)
        record = {
            "messageId": f"notify-{suffix}",
            "body": json.dumps(message),
            "attributes": {"ApproximateReceiveCount": "1"},
        }

        assert notify.handler({"Records": [record]}, None) == {
            "batchItemFailures": []
        }
        assert notify.handler({"Records": [record]}, None) == {
            "batchItemFailures": []
        }
        send.assert_called_once()

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
            assert deliveries[0].ses_message_id == "ses-integration-message"
            assert subscription is not None
            assert subscription.last_delivery_status == "sent"
            assert subscription.last_delivery_error_code is None
    finally:
        if ids:
            _cleanup(engine, ids=ids)
        engine.dispose()
