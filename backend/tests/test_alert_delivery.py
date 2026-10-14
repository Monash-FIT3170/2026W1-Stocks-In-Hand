"""Alert delivery through the notify handler, on Postgres with a fake sender.

Each test drives ``notify.handler`` with SQS records about a fresh ticker,
scrape run and analysed artifact, watched by a fresh investor with a verified
alert subscription. Every database session the worker opens is a savepoint
inside one transaction that the test rolls back, and a RecordingEmailSender
stands in for Brevo.

The daily budget counts every investor's alerts, so the budget tests set it
from the count already in the database.
"""

# pylint: disable=duplicate-code,not-callable,redefined-outer-name,too-many-lines

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import and_, create_engine, delete, func, inspect, or_, select, update
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
    EmailSender,
    Misconfigured,
    OutgoingEmail,
    RecipientRejected,
    RecordingEmailSender,
    SendOutcome,
    Unavailable,
)
from lambdas import notify

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class WatchedArtifact:  # pylint: disable=too-many-instance-attributes
    """An analysed artifact, one investor watching its ticker, and its SQS record."""

    investor_id: uuid.UUID
    email: str
    unsubscribe_token_hash: str
    ticker_id: uuid.UUID
    ticker_symbol: str
    scrape_run_id: uuid.UUID
    artifact_id: uuid.UUID
    record: dict[str, object]

    @property
    def retry(self) -> dict[str, list[dict[str, object]]]:
        """The handler's answer when SQS should deliver this record again."""
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
    monkeypatch.setattr(settings, "ALERT_MAX_PER_INVESTOR_PER_RUN", 5, raising=False)
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


def _send_with(
    monkeypatch: pytest.MonkeyPatch,
    sender: EmailSender,
) -> list[dict[str, object]]:
    """Make ``sender`` the configured sender, and return how notify asked for it."""
    asked: list[dict[str, object]] = []

    def configured_sender(**kwargs: object) -> EmailSender:
        asked.append(kwargs)
        return sender

    monkeypatch.setattr(email_sender, "configured_sender", configured_sender)
    return asked


def _record(
    *,
    artifact_id: uuid.UUID,
    ticker_symbol: str,
    scrape_run_id: uuid.UUID,
    confidence: str = "0.8200",
) -> dict[str, object]:
    """The SQS record the analysis worker publishes for a negative artifact."""
    return {
        "messageId": f"alert-delivery-{uuid.uuid4().hex}",
        "body": json.dumps(
            {
                "schema_version": 1,
                "artifact_id": str(artifact_id),
                "ticker": ticker_symbol,
                "scrape_run_id": str(scrape_run_id),
                "sentiment_label": "negative",
                "confidence_score": confidence,
            }
        ),
        "attributes": {"ApproximateReceiveCount": "1"},
    }


def _add_watcher(
    db: Session,
    ticker_id: uuid.UUID,
    *,
    subscription: dict[str, object] | None = None,
    rule: dict[str, object] | None = None,
) -> tuple[uuid.UUID, str, str]:
    """A new investor watching the ticker, with a verified alert subscription.

    Their rule wants negative artifacts at 0.75 or more. ``subscription`` and
    ``rule`` replace stored values. Returns the investor's id, address and
    unsubscribe token hash.
    """
    suffix = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    email = f"alert-delivery-{suffix}@example.com"
    token_hash = uuid.uuid4().hex + uuid.uuid4().hex
    investor = Investor(email=email, username="Alert delivery test")
    db.add(investor)
    db.flush()
    watchlist = Watchlist(investor_id=investor.id, name="Alert delivery test")
    db.add(watchlist)
    db.flush()
    db.add_all(
        [
            WatchlistTicker(watchlist_id=watchlist.id, ticker_id=ticker_id),
            AlertSubscription(
                **{
                    "investor_id": investor.id,
                    "email": email,
                    "enabled": True,
                    "verification_status": "verified",
                    "verification_requested_at": now,
                    "verified_at": now,
                    "unsubscribe_token_hash": token_hash,
                    **(subscription or {}),
                }
            ),
            AlertRule(
                **{
                    "investor_id": investor.id,
                    "ticker_id": None,
                    "rule_type": "sentiment_threshold",
                    "sentiment_labels": ["negative"],
                    "min_confidence": Decimal("0.7500"),
                    "enabled": True,
                    **(rule or {}),
                }
            ),
        ]
    )
    db.flush()
    return investor.id, email, token_hash


def _watched_artifact(
    session: SessionFactory,
    *,
    confidence: str = "0.8200",
    subscription: dict[str, object] | None = None,
    rule: dict[str, object] | None = None,
) -> WatchedArtifact:
    """A negative artifact at ``confidence``, watched by one new investor.

    ``subscription`` and ``rule`` replace values the investor's verified
    subscription and rule (negative at 0.75) are stored with.
    """
    suffix = uuid.uuid4().hex
    with session() as db:
        ticker = Ticker(
            symbol=f"T{suffix[:8].upper()}",
            company_name="Alert Delivery Test Limited",
            exchange="ASX",
        )
        platform = InformationPlatform(
            name=f"Alert delivery test {suffix}",
            platform_type="test",
        )
        db.add_all([ticker, platform])
        db.flush()
        scrape_run = ScrapeRun(
            platform_id=platform.id,
            ticker_id=ticker.id,
            status="completed",
            idempotency_key=f"alert-delivery:{suffix}",
        )
        db.add(scrape_run)
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
                    confidence_score=Decimal(confidence),
                ),
                ArtifactSummary(
                    artifact_id=artifact.id,
                    summary_text="Earnings were below expectations.",
                ),
            ]
        )
        investor_id, email, token_hash = _add_watcher(
            db,
            ticker.id,
            subscription=subscription,
            rule=rule,
        )
        watched = WatchedArtifact(
            investor_id=investor_id,
            email=email,
            unsubscribe_token_hash=token_hash,
            ticker_id=ticker.id,
            ticker_symbol=str(ticker.symbol),
            scrape_run_id=scrape_run.id,
            artifact_id=artifact.id,
            record=_record(
                artifact_id=artifact.id,
                ticker_symbol=str(ticker.symbol),
                scrape_run_id=scrape_run.id,
                confidence=confidence,
            ),
        )
        db.commit()
    return watched


def _next_artifact(session: SessionFactory, watched: WatchedArtifact) -> WatchedArtifact:
    """Another negative artifact at 0.82 in the same scrape run, for the same investor."""
    with session() as db:
        artifact = Artifact(
            scrape_run_id=watched.scrape_run_id,
            ticker_id=watched.ticker_id,
            artifact_type="announcement",
            title="Quarterly activities report",
            content_hash=f"alert-delivery-{uuid.uuid4().hex}",
            analysis_status="completed",
        )
        db.add(artifact)
        db.flush()
        db.add(
            ArtifactSentiment(
                artifact_id=artifact.id,
                sentiment_label="negative",
                confidence_score=Decimal("0.8200"),
            )
        )
        artifact_id = artifact.id
        db.commit()
    return replace(
        watched,
        artifact_id=artifact_id,
        record=_record(
            artifact_id=artifact_id,
            ticker_symbol=watched.ticker_symbol,
            scrape_run_id=watched.scrape_run_id,
        ),
    )


def _another_watcher(session: SessionFactory, watched: WatchedArtifact) -> WatchedArtifact:
    """The same artifact and record, seen by a second investor watching the ticker."""
    with session() as db:
        investor_id, email, token_hash = _add_watcher(db, watched.ticker_id)
        db.commit()
    return replace(
        watched,
        investor_id=investor_id,
        email=email,
        unsubscribe_token_hash=token_hash,
    )


def _second_watchlist(session: SessionFactory, watched: WatchedArtifact) -> None:
    """Give the investor a second watchlist that also holds the ticker."""
    with session() as db:
        watchlist = Watchlist(investor_id=watched.investor_id, name="Second watchlist")
        db.add(watchlist)
        db.flush()
        db.add(WatchlistTicker(watchlist_id=watchlist.id, ticker_id=watched.ticker_id))
        db.commit()


def _with_message(watched: WatchedArtifact, **changes: str) -> WatchedArtifact:
    """The same artifact and investor, with a record whose message says otherwise."""
    body = {**json.loads(str(watched.record["body"])), **changes}
    return replace(
        watched,
        record={
            **watched.record,
            "messageId": f"alert-delivery-{uuid.uuid4().hex}",
            "body": json.dumps(body),
        },
    )


def _deliver(watched: WatchedArtifact) -> dict[str, list]:
    return notify.handler({"Records": [watched.record]}, None)


def _delivery(session: SessionFactory, watched: WatchedArtifact) -> AlertDelivery:
    with session() as db:
        return db.scalars(
            select(AlertDelivery).where(AlertDelivery.investor_id == watched.investor_id)
        ).one()


def _ledger(session: SessionFactory, watched: WatchedArtifact) -> dict[uuid.UUID | None, str]:
    """Each of the investor's ledger rows' status, by artifact (None for the rollup)."""
    with session() as db:
        return {
            delivery.artifact_id: str(delivery.status)
            for delivery in db.scalars(
                select(AlertDelivery).where(AlertDelivery.investor_id == watched.investor_id)
            )
        }


def _rollup(session: SessionFactory, watched: WatchedArtifact) -> AlertDelivery:
    """The investor's rollup row for the watched artifact's scrape run."""
    with session() as db:
        return db.scalars(
            select(AlertDelivery).where(
                AlertDelivery.investor_id == watched.investor_id,
                AlertDelivery.scrape_run_id == watched.scrape_run_id,
                AlertDelivery.artifact_id.is_(None),
            )
        ).one()


def _subscription(session: SessionFactory, watched: WatchedArtifact) -> AlertSubscription:
    with session() as db:
        return db.scalars(
            select(AlertSubscription).where(
                AlertSubscription.investor_id == watched.investor_id
            )
        ).one()


def _budget_used(session: SessionFactory) -> int:
    """Alerts sent and claims held in the last 24 hours, for every investor."""
    since = func.now() - timedelta(hours=24)
    with session() as db:
        return int(
            db.scalar(
                select(func.count(AlertDelivery.id)).where(
                    or_(
                        and_(
                            AlertDelivery.status == "claimed",
                            AlertDelivery.claimed_at >= since,
                        ),
                        and_(
                            AlertDelivery.status.in_(("sent", "rollup_sent")),
                            AlertDelivery.sent_at >= since,
                        ),
                    )
                )
            )
        )


def _events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    """The structured events the notify worker logged, oldest first."""
    payloads = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.getMessage().startswith("{")
    ]
    return [payload for payload in payloads if payload.get("stage") == "notify"]


def _rollup_left_failed(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[WatchedArtifact, WatchedArtifact]:
    """Two artifacts in one run, with a cap of one alert per investor per run.

    The first artifact's alert is sent. The second is suppressed by the cap,
    and its rollup was refused for now, so the rollup's row is failed and the
    second artifact's record waits to be delivered again.
    """
    monkeypatch.setattr(settings, "ALERT_MAX_PER_INVESTOR_PER_RUN", 1, raising=False)
    first = _watched_artifact(session)
    second = _next_artifact(session, first)
    _send_with(
        monkeypatch,
        RecordingEmailSender([Accepted("direct-1"), Unavailable("rate_limit")]),
    )
    assert _deliver(first) == NO_RETRY
    assert _deliver(second) == second.retry
    assert _ledger(session, first) == {
        first.artifact_id: "sent",
        second.artifact_id: "suppressed_cap",
        None: "failed",
    }
    return first, second


def _save_after_the_claim(  # pylint: disable=too-many-arguments
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    watched: WatchedArtifact,
    model: type[AlertSubscription] | type[AlertRule],
    change: dict[str, object],
    *,
    rollup: bool = False,
) -> list[bool]:
    """Save ``change`` to the investor's preferences once the worker's claim is committed.

    The first session the worker opens after the investor's row for the
    artifact, or for the run's rollup with ``rollup``, is claimed sees the
    change, as a settings save racing the worker would. The list returned
    holds True once the change is saved.
    """
    saved: list[bool] = []
    row = (
        (AlertDelivery.scrape_run_id == watched.scrape_run_id)
        & AlertDelivery.artifact_id.is_(None)
        if rollup
        else AlertDelivery.artifact_id == watched.artifact_id
    )

    @contextmanager
    def saving_after_the_claim() -> Iterator[Session]:
        if not saved:
            with session() as db:
                status = db.scalar(
                    select(AlertDelivery.status).where(
                        AlertDelivery.investor_id == watched.investor_id,
                        row,
                    )
                )
                if status == "claimed":
                    db.execute(
                        update(model)
                        .where(model.investor_id == watched.investor_id)
                        .values(**change)
                    )
                    db.commit()
                    saved.append(True)
        with session() as db:
            yield db

    monkeypatch.setattr(notify, "database_session", saving_after_the_claim)
    return saved


def test_an_accepted_alert_is_recorded_as_sent(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watched = _watched_artifact(session)
    sender = RecordingEmailSender()
    asked = _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY

    # A paced sender shares ALERT_PACER, so live alerts go out a second apart.
    assert asked == [{"paced": True}]
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


def test_a_malformed_brevo_setting_fails_the_alert_and_retries_the_record(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real Brevo sender answers Misconfigured before any request."""
    monkeypatch.setattr(settings, "BREVO_API_KEY", "test-api-key", raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", "alerts@example.com", raising=False)
    monkeypatch.setattr(
        settings,
        "BREVO_API_BASE_URL",
        "https://[api.brevo.com/v3",
        raising=False,
    )
    watched = _watched_artifact(session)

    assert _deliver(watched) == watched.retry

    delivery = _delivery(session, watched)
    assert (delivery.status, delivery.error_code) == (
        "failed",
        "invalid_notification_configuration",
    )


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


def test_a_record_delivered_twice_sends_one_alert(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watched = _watched_artifact(session)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY
    assert _deliver(watched) == NO_RETRY

    assert len(sender.sent) == 1
    assert _ledger(session, watched) == {watched.artifact_id: "sent"}


def test_each_investor_watching_the_ticker_gets_one_alert(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An investor whose two watchlists both hold the ticker still gets one."""
    first = _watched_artifact(session)
    _second_watchlist(session, first)
    second = _another_watcher(session, first)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(first) == NO_RETRY

    assert sorted(email.to for email in sender.sent) == sorted([first.email, second.email])


def test_a_temporary_refusal_for_one_investor_still_alerts_the_others(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = _watched_artifact(session)
    accepted = _another_watcher(session, refused)

    def answer(email: OutgoingEmail) -> SendOutcome:
        if email.to == refused.email:
            return Unavailable("rate_limit")
        return Accepted("accepted-1")

    sender = RecordingEmailSender(answer)
    _send_with(monkeypatch, sender)

    assert _deliver(refused) == refused.retry
    assert sorted(email.to for email in sender.sent) == sorted(
        [refused.email, accepted.email]
    )
    assert _delivery(session, accepted).status == "sent"

    redelivery = RecordingEmailSender()
    _send_with(monkeypatch, redelivery)

    assert _deliver(refused) == NO_RETRY
    assert [email.to for email in redelivery.sent] == [refused.email]


def _sender_raises(_session: SessionFactory, _watched: WatchedArtifact) -> None:
    raise RuntimeError("The sender raised instead of answering an outcome")


def _claim_taken_over(session: SessionFactory, watched: WatchedArtifact) -> None:
    """Another worker takes the investor's claim over, as it may once the claim is stale."""
    with session() as db:
        db.execute(
            update(AlertDelivery)
            .where(AlertDelivery.investor_id == watched.investor_id)
            .values(claimed_at=AlertDelivery.claimed_at + timedelta(seconds=1))
        )
        db.commit()


def _subscription_deleted(session: SessionFactory, watched: WatchedArtifact) -> None:
    with session() as db:
        db.execute(
            delete(AlertSubscription).where(
                AlertSubscription.investor_id == watched.investor_id
            )
        )
        db.commit()


@pytest.mark.parametrize(
    ("interrupt", "retry_code"),
    [
        pytest.param(_sender_raises, "RuntimeError", id="sender raises"),
        pytest.param(_claim_taken_over, "delivery_lease_lost", id="claim taken over"),
        pytest.param(
            _subscription_deleted,
            "subscription_state_changed",
            id="subscription deleted",
        ),
    ],
)
def test_an_attempt_that_fails_after_its_claim_still_alerts_the_others(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    interrupt: Callable[[SessionFactory, WatchedArtifact], None],
    retry_code: str,
) -> None:
    """The first investor's attempt breaks while their email goes out.

    Whichever investor comes first, the other still gets the alert, and the
    record is retried with the failed attempt's code.
    """
    first = _watched_artifact(session)
    second = _another_watcher(session, first)
    watchers = {first.email: first, second.email: second}
    interrupted: list[WatchedArtifact] = []

    def answer(email: OutgoingEmail) -> SendOutcome:
        if not interrupted:
            interrupted.append(watchers[email.to])
            interrupt(session, watchers[email.to])
        return Accepted("accepted-1")

    sender = RecordingEmailSender(answer)
    _send_with(monkeypatch, sender)

    assert _deliver(first) == first.retry

    assert len(interrupted) == 1
    failed = interrupted[0]
    other = second if failed is first else first
    assert sorted(email.to for email in sender.sent) == sorted([first.email, second.email])
    assert _delivery(session, other).status == "sent"
    # The failed attempt recorded nothing, so its claim stands until it is stale.
    assert _ledger(session, failed) == {failed.artifact_id: "claimed"}
    assert [(event["event"], event["error_code"]) for event in _events(caplog)] == [
        ("record_retry", retry_code)
    ]


@pytest.mark.parametrize(
    ("confidence", "subscription", "rule"),
    [
        pytest.param("0.8200", {"enabled": False}, None, id="alerts off"),
        pytest.param("0.8200", None, {"enabled": False}, id="rule off"),
        pytest.param(
            "0.8200",
            None,
            {"sentiment_labels": ["positive"]},
            id="label not chosen",
        ),
        pytest.param("0.7499", None, None, id="below the threshold"),
    ],
)
def test_an_artifact_the_rule_does_not_want_leaves_no_ledger_row(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    confidence: str,
    subscription: dict[str, object] | None,
    rule: dict[str, object] | None,
) -> None:
    watched = _watched_artifact(
        session,
        confidence=confidence,
        subscription=subscription,
        rule=rule,
    )
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY

    assert sender.sent == []
    assert _ledger(session, watched) == {}


def test_an_artifact_at_the_threshold_is_alerted(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watched = _watched_artifact(session, confidence="0.7500")
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY

    assert len(sender.sent) == 1
    assert _ledger(session, watched) == {watched.artifact_id: "sent"}


@pytest.mark.parametrize("verification_status", ["unverified", "pending", "failed"])
def test_an_unverified_address_is_rejected_without_an_email(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    verification_status: str,
) -> None:
    watched = _watched_artifact(
        session,
        subscription={"verification_status": verification_status, "verified_at": None},
    )
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY

    assert sender.sent == []
    delivery = _delivery(session, watched)
    assert (delivery.status, delivery.error_code) == ("rejected", "recipient_not_verified")
    subscription = _subscription(session, watched)
    assert (
        subscription.last_delivery_status,
        subscription.last_delivery_error_code,
    ) == ("rejected", "recipient_not_verified")


def test_past_the_per_run_cap_the_investor_gets_one_rollup(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ALERT_MAX_PER_INVESTOR_PER_RUN", 1, raising=False)
    first = _watched_artifact(session)
    second = _next_artifact(session, first)
    third = _next_artifact(session, first)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    batch = {"Records": [first.record, second.record, third.record]}
    assert notify.handler(batch, None) == NO_RETRY

    direct, rollup = sender.sent
    assert "Half year results" in direct.text
    assert "At least 1 more matching signal arrived" in rollup.text
    assert _ledger(session, first) == {
        first.artifact_id: "sent",
        second.artifact_id: "suppressed_cap",
        third.artifact_id: "suppressed_cap",
        None: "rollup_sent",
    }
    # The newest outcome is the third artifact's suppression.
    subscription = _subscription(session, first)
    assert (
        subscription.last_delivery_status,
        subscription.last_delivery_error_code,
    ) == ("suppressed_cap", "per_run_cap")


def test_a_rollup_refused_for_now_is_sent_on_redelivery_without_another_alert(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = _rollup_left_failed(session, monkeypatch)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(second) == NO_RETRY
    [rollup] = sender.sent
    assert "At least 1 more matching signal arrived" in rollup.text
    assert _ledger(session, first) == {
        first.artifact_id: "sent",
        second.artifact_id: "suppressed_cap",
        None: "rollup_sent",
    }


def test_a_rollup_redelivered_after_the_address_changed_is_rejected(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rollup checks the address is confirmed, as the investor's first alert did."""
    _, second = _rollup_left_failed(session, monkeypatch)
    with session() as db:
        db.execute(
            update(AlertSubscription)
            .where(AlertSubscription.investor_id == second.investor_id)
            .values(
                email=f"changed-{uuid.uuid4().hex}@example.com",
                verification_status="pending",
                verified_at=None,
            )
        )
        db.commit()
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(second) == NO_RETRY

    assert sender.sent == []
    rollup = _rollup(session, second)
    assert (rollup.status, rollup.error_code) == ("rejected", "recipient_not_verified")


def test_a_rollup_redelivered_at_the_daily_budget_is_suppressed_for_good(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, second = _rollup_left_failed(session, monkeypatch)
    monkeypatch.setattr(settings, "ALERT_DAILY_BUDGET", _budget_used(session), raising=False)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(second) == NO_RETRY
    assert _deliver(second) == NO_RETRY

    assert sender.sent == []
    rollup = _rollup(session, second)
    assert (rollup.status, rollup.error_code) == ("suppressed_budget", "daily_budget")
    suppressed = [event for event in _events(caplog) if event["event"] == "suppressed"]
    assert [
        (event["investor_id"], event["kind"], event["reason"]) for event in suppressed
    ] == [(str(second.investor_id), "rollup", "daily_budget")]


def test_preferences_saved_after_the_rollup_claim_reject_the_rollup(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, second = _rollup_left_failed(session, monkeypatch)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    saved = _save_after_the_claim(
        session,
        monkeypatch,
        second,
        AlertRule,
        {"min_confidence": Decimal("0.8000")},
        rollup=True,
    )

    assert _deliver(second) == NO_RETRY

    assert saved
    assert sender.sent == []
    rollup = _rollup(session, second)
    assert (rollup.status, rollup.error_code) == ("rejected", "preferences_changed")


def test_at_the_daily_budget_the_alert_is_suppressed_for_good(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    watched = _watched_artifact(session)
    monkeypatch.setattr(settings, "ALERT_DAILY_BUDGET", _budget_used(session), raising=False)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY
    assert _deliver(watched) == NO_RETRY

    assert sender.sent == []
    delivery = _delivery(session, watched)
    assert (delivery.status, delivery.error_code) == ("suppressed_budget", "daily_budget")
    suppressed = [event for event in _events(caplog) if event["event"] == "suppressed"]
    assert [(event["investor_id"], event["reason"]) for event in suppressed] == [
        (str(watched.investor_id), "daily_budget")
    ]


def test_the_alert_that_reaches_the_daily_budget_is_sent(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget counts the alert's own claim, so that claim may take the last place."""
    watched = _watched_artifact(session)
    monkeypatch.setattr(
        settings,
        "ALERT_DAILY_BUDGET",
        _budget_used(session) + 1,
        raising=False,
    )
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY

    assert len(sender.sent) == 1
    assert _delivery(session, watched).status == "sent"


@pytest.mark.parametrize(
    ("model", "change"),
    [
        pytest.param(AlertSubscription, {"enabled": False}, id="alerts turned off"),
        pytest.param(
            AlertRule,
            {"min_confidence": Decimal("0.8000")},
            id="rule changed but still matching",
        ),
    ],
)
def test_preferences_saved_after_the_claim_reject_the_alert(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    model: type[AlertSubscription] | type[AlertRule],
    change: dict[str, object],
) -> None:
    watched = _watched_artifact(session)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    saved = _save_after_the_claim(session, monkeypatch, watched, model, change)

    assert _deliver(watched) == NO_RETRY

    assert saved
    assert sender.sent == []
    delivery = _delivery(session, watched)
    assert (delivery.status, delivery.error_code) == ("rejected", "preferences_changed")


def test_a_record_about_an_artifact_not_visible_yet_is_retried(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watched = _watched_artifact(session)
    unseen = _with_message(watched, artifact_id=str(uuid.uuid4()))
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(unseen) == unseen.retry

    assert sender.sent == []
    assert _ledger(session, watched) == {}


@pytest.mark.parametrize(
    "disagreement",
    [
        pytest.param({"sentiment_label": "positive"}, id="label"),
        pytest.param({"confidence_score": "0.9000"}, id="confidence"),
        pytest.param({"ticker": "ZZZZZ"}, id="ticker"),
        pytest.param({"scrape_run_id": str(uuid.uuid4())}, id="scrape run"),
    ],
)
def test_a_record_that_disagrees_with_the_artifact_is_dropped(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    disagreement: dict[str, str],
) -> None:
    watched = _with_message(_watched_artifact(session), **disagreement)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY

    assert sender.sent == []
    assert _ledger(session, watched) == {}


def test_switched_off_alerts_open_no_database_session_and_send_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_database() -> AbstractContextManager[Session]:
        raise AssertionError("the worker opened a database session")

    monkeypatch.setattr(notify, "database_session", no_database)
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False, raising=False)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    record = _record(
        artifact_id=uuid.uuid4(),
        ticker_symbol="BHP",
        scrape_run_id=uuid.uuid4(),
    )

    assert notify.handler({"Records": [record]}, None) == NO_RETRY

    assert sender.sent == []


def test_only_the_record_that_needs_a_retry_is_returned_for_retry(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _watched_artifact(session)
    unseen = _with_message(first, artifact_id=str(uuid.uuid4()))
    last = _watched_artifact(session)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    batch = {"Records": [first.record, unseen.record, last.record]}
    assert notify.handler(batch, None) == unseen.retry

    assert sorted(email.to for email in sender.sent) == sorted([first.email, last.email])


def test_the_alert_links_to_the_ticker_news_and_a_signed_unsubscribe_page(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watched = _watched_artifact(session)
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    assert _deliver(watched) == NO_RETRY

    [email] = sender.sent
    assert email.unsubscribe_url is not None
    assert email.unsubscribe_url.startswith("https://app.example.test/unsubscribe/?t=v1.")
    # The link carries a signature made with the stored hash, never the hash.
    assert watched.unsubscribe_token_hash not in email.unsubscribe_url
    news_url = f"https://app.example.test/ticker/{watched.ticker_symbol}/news/"
    assert news_url in email.text
    assert news_url in email.html


def test_a_failing_delivery_never_logs_the_investors_address(
    session: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    watched = _watched_artifact(session)
    _send_with(monkeypatch, RecordingEmailSender([Unavailable("rate_limit")]))

    assert _deliver(watched) == watched.retry

    assert [(event["event"], event["error_code"]) for event in _events(caplog)] == [
        ("record_retry", "rate_limit")
    ]
    assert watched.email not in caplog.text
