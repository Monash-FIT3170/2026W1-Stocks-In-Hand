"""The alert subscription lifecycle, through the routes on Postgres with a fake email sender.

Each test signs in a fresh investor and calls the notification routes through
the FastAPI app. Every database session a request opens is a savepoint inside
one transaction that the test rolls back, and a RecordingEmailSender stands
in for Brevo. The tests that look from another connection while an email goes
out commit for real instead, and delete the investor afterwards.
"""

# pylint: disable=duplicate-code,redefined-outer-name

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import main
from app.api.deps import get_current_investor
from app.core.config import settings
from app.database.connection import get_db
from app.models.alert_delivery import AlertDelivery
from app.models.alert_rule import AlertRule
from app.models.alert_subscription import AlertSubscription
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.information_platform import InformationPlatform
from app.models.investor import Investor
from app.models.scrape_run import ScrapeRun
from app.models.ticker import Ticker
from app.models.watchlist import Watchlist
from app.models.watchlist_ticker import WatchlistTicker
from app.schemas.notification import NotificationPreferencesUpdate
from app.services import email_sender
from app.services.alert_subscriptions import alert_links
from app.services.alert_tokens import unsubscribe_token, verification_token
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
from app.sources import SOURCES
from lambdas import notify
from tools.template_model import template_model

ENABLE_ALERTS = {
    "enabled": True,
    "sentiment_labels": ["negative"],
    "min_confidence": 0.75,
}
UNSUBSCRIBED = {"message": "If the token was valid, notifications are now disabled."}
INVALID_LINK = {"detail": "The verification link is invalid or expired."}
NO_RETRY: dict[str, list] = {"batchItemFailures": []}
# The application name of every connection the routes open, so a test can
# find them in pg_stat_activity.
ROUTE_CONNECTIONS = "alert-subscription-routes"
SITE_PAGES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "app"


@dataclass(frozen=True)
class Api:
    """The app as one signed-in investor sees it, and the database behind it."""

    client: TestClient
    investor: SimpleNamespace
    session: Callable[[], AbstractContextManager[Session]]

    def preferences(self) -> dict:
        response = self.client.get("/notifications/preferences")
        assert response.status_code == 200
        return response.json()


@pytest.fixture()
def engine() -> Iterator[Engine]:
    """The configured database, or a skip when it is not there."""
    database = create_engine(
        settings.DATABASE_URL,
        connect_args={"application_name": ROUTE_CONNECTIONS},
    )
    try:
        with database.connect() as probe:
            if not inspect(probe).has_table("alert_subscriptions"):
                database.dispose()
                pytest.skip("Alert migrations are not applied")
    except OperationalError as exc:
        database.dispose()
        pytest.skip(f"PostgreSQL is unavailable: {exc}")
    try:
        yield database
    finally:
        database.dispose()


@contextmanager
def _signed_in(
    session: Callable[[], AbstractContextManager[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Api]:
    """A new investor signed in to the app, whose requests use ``session``."""
    email = f"alert-subscription-{uuid.uuid4().hex}@example.com"
    with session() as db:
        investor = Investor(email=email, username="Alert subscription test")
        db.add(investor)
        db.flush()
        account = SimpleNamespace(id=investor.id, email=email)
        db.commit()

    def request_session() -> Iterator[Session]:
        with session() as db:
            yield db

    main.app.dependency_overrides[get_db] = request_session
    main.app.dependency_overrides[get_current_investor] = lambda: account
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings,
        "FRONTEND_BASE_URL",
        "https://app.example.test",
        raising=False,
    )
    try:
        yield Api(client=TestClient(main.app), investor=account, session=session)
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main.app.dependency_overrides.pop(get_current_investor, None)


@pytest.fixture()
def api(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    connection = engine.connect()
    outer = connection.begin()

    @contextmanager
    def session() -> Iterator[Session]:
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    try:
        with _signed_in(session, monkeypatch) as signed_in:
            yield signed_in
    finally:
        outer.rollback()
        connection.close()


@pytest.fixture()
def committed_api(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    """Like ``api``, but every session commits for real."""

    @contextmanager
    def session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    with _signed_in(session, monkeypatch) as signed_in:
        try:
            yield signed_in
        finally:
            # The investor's alert subscription and rule go with it.
            with session() as db:
                db.execute(delete(Investor).where(Investor.id == signed_in.investor.id))
                db.commit()


def _send_with(monkeypatch: pytest.MonkeyPatch, sender: EmailSender) -> None:
    monkeypatch.setattr(email_sender, "configured_sender", lambda **_: sender)


def _link_token(link: str) -> str:
    return parse_qs(urlsplit(link).query)["t"][0]


def _verification_link(email: OutgoingEmail) -> str:
    return next(
        line for line in email.text.splitlines() if "/verify-notifications/" in line
    )


def _verification_token(email: OutgoingEmail) -> str:
    link = _verification_link(email)
    assert link.startswith("https://app.example.test/verify-notifications/?t=")
    return _link_token(link)


def _verify(api: Api, email: OutgoingEmail) -> httpx.Response:
    """Open the verification link in ``email``."""
    return api.client.post(
        "/notifications/verify",
        json={"token": _verification_token(email)},
    )


def _token_hash() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


def _subscription(api: Api) -> AlertSubscription:
    with api.session() as db:
        return db.scalars(
            select(AlertSubscription).where(
                AlertSubscription.investor_id == api.investor.id
            )
        ).one()


def _enabled(api: Api, subscription_id: uuid.UUID) -> bool:
    with api.session() as db:
        return bool(
            db.scalar(
                select(AlertSubscription.enabled).where(
                    AlertSubscription.id == subscription_id
                )
            )
        )


def _requested_minutes_ago(api: Api, minutes: int) -> None:
    """Move the investor's last verification request ``minutes`` further into the past."""
    with api.session() as db:
        db.execute(
            update(AlertSubscription)
            .where(AlertSubscription.investor_id == api.investor.id)
            .values(
                verification_requested_at=AlertSubscription.verification_requested_at
                - timedelta(minutes=minutes)
            )
        )
        db.commit()


def _failed_verification(api: Api) -> None:
    """Enabled alerts whose last verification email, two minutes ago, was not sent."""
    with api.session() as db:
        db.add_all(
            [
                AlertSubscription(
                    investor_id=api.investor.id,
                    email=api.investor.email,
                    enabled=True,
                    verification_status="failed",
                    verification_requested_at=(
                        datetime.now(timezone.utc) - timedelta(minutes=2)
                    ),
                    unsubscribe_token_hash=_token_hash(),
                ),
                AlertRule(
                    investor_id=api.investor.id,
                    ticker_id=None,
                    rule_type="sentiment_threshold",
                    sentiment_labels=["negative"],
                    min_confidence=Decimal("0.7500"),
                    enabled=True,
                ),
            ]
        )
        db.commit()


def _pending_since(api: Api, requested_at: datetime) -> str:
    """Enabled alerts waiting for the verification requested at ``requested_at``.

    Returns the token of that request's verification link.
    """
    token_hash = _token_hash()
    with api.session() as db:
        subscription = AlertSubscription(
            investor_id=api.investor.id,
            email=api.investor.email,
            enabled=True,
            verification_status="pending",
            verification_requested_at=requested_at,
            unsubscribe_token_hash=token_hash,
        )
        db.add(subscription)
        db.flush()
        subscription_id = subscription.id
        db.commit()
    return verification_token(subscription_id, token_hash, requested_at)


def _another_subscription(api: Api) -> tuple[uuid.UUID, str]:
    """Another investor's enabled alerts. Returns the subscription's id and token hash."""
    token_hash = _token_hash()
    with api.session() as db:
        investor = Investor(
            email=f"alert-subscription-{uuid.uuid4().hex}@example.com",
            username="Another alert subscriber",
        )
        db.add(investor)
        db.flush()
        subscription = AlertSubscription(
            investor_id=investor.id,
            email=investor.email,
            enabled=True,
            verification_status="verified",
            unsubscribe_token_hash=token_hash,
        )
        db.add(subscription)
        db.flush()
        subscription_id = subscription.id
        db.commit()
    return subscription_id, token_hash


def _analysed_artifacts(api: Api, count: int) -> list[tuple[uuid.UUID, dict[str, object]]]:
    """``count`` negative artifacts in one scrape run of a new ticker the investor watches.

    Returns each artifact's id and the SQS record that announces its analysis.
    """
    suffix = uuid.uuid4().hex
    symbol = f"T{suffix[:8].upper()}"
    announced = []
    with api.session() as db:
        ticker = Ticker(
            symbol=symbol,
            company_name="Alert Subscription Test Limited",
            exchange="ASX",
        )
        platform = InformationPlatform(
            name=f"Alert subscription test {suffix}",
            platform_type="test",
        )
        db.add_all([ticker, platform])
        db.flush()
        scrape_run = ScrapeRun(
            platform_id=platform.id,
            ticker_id=ticker.id,
            status="completed",
            idempotency_key=f"alert-subscription:{suffix}",
        )
        watchlist = Watchlist(investor_id=api.investor.id, name="Alert subscription test")
        db.add_all([scrape_run, watchlist])
        db.flush()
        db.add(WatchlistTicker(watchlist_id=watchlist.id, ticker_id=ticker.id))
        for number in range(count):
            artifact = Artifact(
                scrape_run_id=scrape_run.id,
                ticker_id=ticker.id,
                artifact_type="announcement",
                title=f"Announcement {number + 1}",
                content_hash=f"alert-subscription-{suffix}-{number}",
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
            message = {
                "schema_version": 1,
                "artifact_id": str(artifact.id),
                "ticker": symbol,
                "scrape_run_id": str(scrape_run.id),
                "sentiment_label": "negative",
                "confidence_score": "0.8200",
            }
            announced.append(
                (
                    artifact.id,
                    {
                        "messageId": f"alert-subscription-{uuid.uuid4().hex}",
                        "body": json.dumps(message),
                        "attributes": {"ApproximateReceiveCount": "1"},
                    },
                )
            )
        db.commit()
    return announced


def _ledger(api: Api) -> dict[uuid.UUID | None, str]:
    """Each of the investor's delivery ledger rows' status, by artifact."""
    with api.session() as db:
        return {
            delivery.artifact_id: str(delivery.status)
            for delivery in db.scalars(
                select(AlertDelivery).where(AlertDelivery.investor_id == api.investor.id)
            )
        }


def test_the_preferences_schema_refuses_duplicate_labels_and_bad_confidence() -> None:
    with pytest.raises(ValidationError):
        NotificationPreferencesUpdate(
            enabled=True,
            sentiment_labels=["negative", "negative"],
        )
    with pytest.raises(ValidationError):
        NotificationPreferencesUpdate(
            enabled=True,
            min_confidence=1.01,
        )


def test_a_new_investor_has_alerts_off_with_the_default_rule(api: Api) -> None:
    assert api.preferences() == {
        "feature_enabled": True,
        "enabled": False,
        "email": api.investor.email,
        "min_confidence": 0.75,
        "sentiment_labels": ["negative"],
        "verification_status": "unverified",
        "verification_requested_at": None,
        "verified_at": None,
        "last_delivery_status": None,
        "last_delivery_error_code": None,
        "last_delivery_at": None,
        "unsubscribe_token": None,
    }


def test_enabling_alerts_emails_a_link_that_verifies_the_address(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    saved = api.client.put("/notifications/preferences", json=ENABLE_ALERTS)

    assert saved.status_code == 200
    assert saved.json()["verification_status"] == "pending"
    assert [email.to for email in sender.sent] == [api.investor.email]

    verified = _verify(api, sender.sent[0])

    assert verified.status_code == 200
    assert api.preferences()["verification_status"] == "verified"
    # Opening the link again changes nothing and answers the same.
    assert _verify(api, sender.sent[0]).json() == verified.json()


def test_an_investor_verifies_gets_an_alert_and_unsubscribes_through_its_link(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    monkeypatch.setattr(notify, "database_session", api.session)
    monkeypatch.setattr(settings, "ALERT_DAILY_BUDGET", 100_000, raising=False)
    assert api.client.put("/notifications/preferences", json=ENABLE_ALERTS).status_code == 200
    assert _verify(api, sender.sent[0]).status_code == 200
    (alerted, first_record), (_, later_record) = _analysed_artifacts(api, 2)

    assert notify.handler({"Records": [first_record]}, None) == NO_RETRY

    alert = sender.sent[-1]
    assert alert.to == api.investor.email
    assert alert.unsubscribe_url is not None
    unsubscribed = api.client.post(
        "/notifications/unsubscribe",
        json={"token": _link_token(alert.unsubscribe_url)},
    )
    assert (unsubscribed.status_code, unsubscribed.json()) == (200, UNSUBSCRIBED)
    assert api.preferences()["enabled"] is False

    assert notify.handler({"Records": [later_record]}, None) == NO_RETRY

    assert len(sender.sent) == 2
    assert _ledger(api) == {alerted: "sent"}


def test_the_first_enable_returns_the_unsubscribe_token_once_and_stores_its_hash(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _send_with(monkeypatch, RecordingEmailSender())

    tokens = [
        api.client.put("/notifications/preferences", json=body).json()["unsubscribe_token"]
        for body in (ENABLE_ALERTS, {**ENABLE_ALERTS, "enabled": False}, ENABLE_ALERTS)
    ]

    first = tokens[0]
    assert first is not None
    assert tokens[1:] == [None, None]
    assert _subscription(api).unsubscribe_token_hash == hashlib.sha256(
        first.encode("utf-8")
    ).hexdigest()


def test_while_alerts_are_switched_off_they_cannot_be_enabled(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False, raising=False)

    enabled = api.client.put("/notifications/preferences", json=ENABLE_ALERTS)
    resent = api.client.post("/notifications/preferences/resend-verification")
    disabled = api.client.put(
        "/notifications/preferences",
        json={**ENABLE_ALERTS, "enabled": False},
    )

    assert (enabled.status_code, enabled.json()) == (
        503,
        {"detail": "Notifications are not enabled"},
    )
    assert resent.status_code == 503
    assert disabled.status_code == 200
    assert sender.sent == []
    preferences = api.preferences()
    assert (
        preferences["feature_enabled"],
        preferences["enabled"],
        preferences["verification_status"],
    ) == (False, False, "unverified")


def test_saving_twice_within_a_minute_sends_one_verification_email(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)

    first = api.client.put("/notifications/preferences", json=ENABLE_ALERTS)
    second = api.client.put(
        "/notifications/preferences",
        json={**ENABLE_ALERTS, "sentiment_labels": ["negative", "neutral"]},
    )

    assert (first.status_code, second.status_code) == (200, 200)
    assert len(sender.sent) == 1
    assert second.json()["verification_status"] == "pending"
    assert second.json()["sentiment_labels"] == ["negative", "neutral"]


def test_a_resend_within_a_minute_answers_429_with_retry_after(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    api.client.put("/notifications/preferences", json=ENABLE_ALERTS)

    response = api.client.post("/notifications/preferences/resend-verification")

    assert response.status_code == 429
    assert response.json() == {"detail": "Verification was requested recently"}
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert len(sender.sent) == 1


def test_a_resend_after_a_minute_sends_a_new_link_and_the_old_one_stops_working(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    api.client.put("/notifications/preferences", json=ENABLE_ALERTS)
    _requested_minutes_ago(api, 2)

    resent = api.client.post("/notifications/preferences/resend-verification")

    assert resent.status_code == 200
    assert resent.json()["verification_status"] == "pending"
    old_email, new_email = sender.sent
    old_link = _verify(api, old_email)
    assert (old_link.status_code, old_link.json()) == (400, INVALID_LINK)
    assert _verify(api, new_email).status_code == 200
    assert api.preferences()["verification_status"] == "verified"


def test_a_link_older_than_its_lifetime_answers_400(api: Api) -> None:
    lifetime = timedelta(hours=settings.ALERT_VERIFICATION_TOKEN_TTL_HOURS)
    token = _pending_since(api, datetime.now(timezone.utc) - lifetime - timedelta(minutes=1))

    response = api.client.post("/notifications/verify", json={"token": token})

    assert (response.status_code, response.json()) == (400, INVALID_LINK)
    assert api.preferences()["verification_status"] == "pending"


def test_a_link_for_a_request_marked_failed_answers_400(api: Api) -> None:
    """The email service said the email was not sent, but its link arrived anyway.

    The link is for the newest request and still fresh, but that request is
    no longer pending, so the investor has to ask for a new link.
    """
    _failed_verification(api)
    subscription = _subscription(api)
    token = verification_token(
        subscription.id,
        str(subscription.unsubscribe_token_hash),
        subscription.verification_requested_at,
    )

    response = api.client.post("/notifications/verify", json={"token": token})

    assert (response.status_code, response.json()) == (400, INVALID_LINK)
    assert api.preferences()["verification_status"] == "failed"


def test_an_internationalised_address_saved_twice_within_a_minute_gets_one_link(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account keeps the domain in Unicode, as sign-up stores it.

    The subscription keeps it in ASCII, so the two must be compared in one form.
    """
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    local_part = f"alerts-{uuid.uuid4().hex[:12]}"
    api.investor.email = f"{local_part}@b\u00fccher.de"

    first = api.client.put("/notifications/preferences", json=ENABLE_ALERTS)
    second = api.client.put("/notifications/preferences", json=ENABLE_ALERTS)

    assert (first.status_code, second.status_code) == (200, 200)
    assert [email.to for email in sender.sent] == [f"{local_part}@xn--bcher-kva.de"]
    assert _subscription(api).email == f"{local_part}@xn--bcher-kva.de"


def test_an_account_address_that_cannot_receive_alerts_answers_422_and_saves_nothing(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alerts go out without SMTPUTF8, so a non-ASCII name before the @ cannot get them."""
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    api.investor.email = f"\u00e9lise-{uuid.uuid4().hex[:12]}@example.com"

    response = api.client.put("/notifications/preferences", json=ENABLE_ALERTS)

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "The email address on your account cannot receive alerts."},
    )
    assert sender.sent == []
    with api.session() as db:
        for model in (AlertSubscription, AlertRule):
            assert db.scalars(
                select(model).where(model.investor_id == api.investor.id)
            ).all() == []


def test_a_link_sent_to_a_replaced_address_cannot_verify_the_new_one(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    old_address = api.investor.email
    api.client.put("/notifications/preferences", json=ENABLE_ALERTS)
    api.investor.email = f"replaced-{uuid.uuid4().hex}@example.com"

    api.client.put("/notifications/preferences", json=ENABLE_ALERTS)

    old_email, new_email = sender.sent
    assert (old_email.to, new_email.to) == (old_address, api.investor.email)
    old_link = _verify(api, old_email)
    assert (old_link.status_code, old_link.json()) == (400, INVALID_LINK)
    preferences = api.preferences()
    assert (preferences["email"], preferences["verification_status"]) == (
        api.investor.email,
        "pending",
    )
    assert _verify(api, new_email).status_code == 200
    assert api.preferences()["verification_status"] == "verified"


def test_every_unsubscribe_token_gets_one_answer_and_turns_off_only_its_own_alerts(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _send_with(monkeypatch, RecordingEmailSender())
    raw_token = api.client.put("/notifications/preferences", json=ENABLE_ALERTS).json()[
        "unsubscribe_token"
    ]
    own_id = _subscription(api).id
    other_id, other_hash = _another_subscription(api)
    tokens = {
        "invalid": "invalid-token-value-123456",
        "unknown subscription": unsubscribe_token(uuid.uuid4(), "f" * 64),
        "forged": unsubscribe_token(own_id, "f" * 64),
        "signed": unsubscribe_token(other_id, other_hash),
        "raw": raw_token,
    }

    still_enabled = {}
    for name, token in tokens.items():
        response = api.client.post("/notifications/unsubscribe", json={"token": token})
        assert (response.status_code, response.json()) == (200, UNSUBSCRIBED)
        still_enabled[name] = (_enabled(api, own_id), _enabled(api, other_id))

    assert still_enabled == {
        "invalid": (True, True),
        "unknown subscription": (True, True),
        "forged": (True, True),
        "signed": (True, False),
        "raw": (False, False),
    }


def test_settings_need_a_session_but_the_email_links_do_not(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    raw_token = api.client.put("/notifications/preferences", json=ENABLE_ALERTS).json()[
        "unsubscribe_token"
    ]
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "legacy", raising=False)
    main.app.dependency_overrides.pop(get_current_investor)

    assert api.client.get("/notifications/preferences").status_code == 401
    assert api.client.put("/notifications/preferences", json=ENABLE_ALERTS).status_code == 401
    assert api.client.post("/notifications/preferences/resend-verification").status_code == 401
    assert _verify(api, sender.sent[0]).status_code == 200
    assert api.client.post(
        "/notifications/unsubscribe",
        json={"token": raw_token},
    ).json() == UNSUBSCRIBED
    subscription = _subscription(api)
    assert (subscription.verification_status, subscription.enabled) == ("verified", False)


def _site_page(path: str) -> Path | None:
    """The page under frontend/src/app that renders ``path``, if there is one."""
    directory = SITE_PAGES
    for segment in filter(None, path.split("/")):
        dynamic = [
            child
            for child in directory.iterdir()
            if child.is_dir() and child.name.startswith("[")
        ]
        if (directory / segment).is_dir():
            directory = directory / segment
        elif len(dynamic) == 1:
            directory = dynamic[0]
        else:
            return None
    page = directory / "page.jsx"
    return page if page.is_file() else None


def _cloudfront_serves(path: str) -> bool:
    """Whether the CloudFront route function serves a page for ``path``, not the 404 page."""
    code = template_model().properties("FrontendRouteFunction")["FunctionCode"]
    static_routes = set(
        re.findall(
            r"'([^']+)': true",
            code.split("var staticRoutes = {", 1)[1].split("};", 1)[0],
        )
    )
    ticker_route = re.search(r"var tickerRoute = /(.+)/;", code)
    assert ticker_route is not None
    route = path.rstrip("/") or "/"
    return route in static_routes or re.fullmatch(ticker_route.group(1), route) is not None


def test_every_link_in_an_alert_or_verification_email_opens_a_page_the_site_serves(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = RecordingEmailSender()
    _send_with(monkeypatch, sender)
    api.client.put("/notifications/preferences", json=ENABLE_ALERTS)
    links = [_verification_link(sender.sent[0])]
    for symbol in SOURCES:
        alert = alert_links(
            subscription_id=uuid.uuid4(),
            unsubscribe_token_hash=_token_hash(),
            ticker_symbol=symbol,
        )
        links += [alert.news_url, alert.unsubscribe_url]

    for link in links:
        parts = urlsplit(link)
        assert f"{parts.scheme}://{parts.netloc}" == "https://app.example.test", link
        assert _site_page(parts.path) is not None, link
        assert _cloudfront_serves(parts.path), link


def _save(api: Api) -> httpx.Response:
    return api.client.put("/notifications/preferences", json=ENABLE_ALERTS)


def _resend_after_a_failure(api: Api) -> httpx.Response:
    _failed_verification(api)
    return api.client.post("/notifications/preferences/resend-verification")


@pytest.mark.parametrize("request_verification", [_save, _resend_after_a_failure])
def test_a_verification_request_is_committed_before_its_email_goes_out(
    committed_api: Api,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    request_verification: Callable[[Api], httpx.Response],
) -> None:
    """Another connection sees the request as pending while the email goes out.

    So a second request within the minute is refused, and the route holds no
    open transaction, and no lock, while it waits for the email service.
    """
    seen: list[tuple[str | None, int]] = []

    def answer(_email: OutgoingEmail) -> SendOutcome:
        with engine.connect() as connection:
            status = connection.scalar(
                select(AlertSubscription.verification_status).where(
                    AlertSubscription.investor_id == committed_api.investor.id
                )
            )
            open_transactions = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database()"
                    " AND application_name = :name"
                    " AND state LIKE 'idle in transaction%'"
                    " AND pid <> pg_backend_pid()"
                ),
                {"name": ROUTE_CONNECTIONS},
            )
        seen.append((status, int(open_transactions or 0)))
        return Accepted("recorded-1")

    _send_with(monkeypatch, RecordingEmailSender(answer))

    response = request_verification(committed_api)

    assert response.status_code == 200
    assert seen == [("pending", 0)]


@pytest.mark.parametrize(
    ("outcome", "status_code"),
    [
        (RecipientRejected("invalid_parameter"), 422),
        (Unavailable("too_many_requests"), 502),
        (Misconfigured("unauthorized"), 500),
    ],
)
def test_an_unsent_verification_email_answers_by_its_outcome(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
    outcome: RecipientRejected | Unavailable | Misconfigured,
    status_code: int,
) -> None:
    _send_with(monkeypatch, RecordingEmailSender([outcome]))

    response = api.client.put("/notifications/preferences", json=ENABLE_ALERTS)

    assert response.status_code == status_code
    preferences = api.preferences()
    assert preferences["enabled"] is True
    assert preferences["verification_status"] == "failed"


def test_a_malformed_brevo_setting_answers_500_and_fails_verification(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real Brevo sender answers Misconfigured before any request."""
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "BREVO_API_KEY", "test-api-key", raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", "alerts@example.com", raising=False)
    monkeypatch.setattr(
        settings,
        "BREVO_API_BASE_URL",
        "https://[api.brevo.com/v3",
        raising=False,
    )

    response = api.client.put("/notifications/preferences", json=ENABLE_ALERTS)

    assert response.status_code == 500
    assert response.json() == {"detail": "Email verification is not configured"}
    assert api.preferences()["verification_status"] == "failed"


def test_a_resend_the_provider_refuses_answers_422(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _failed_verification(api)
    sender = RecordingEmailSender([RecipientRejected("invalid_parameter")])
    _send_with(monkeypatch, sender)

    response = api.client.post("/notifications/preferences/resend-verification")

    assert response.status_code == 422
    assert [email.to for email in sender.sent] == [api.investor.email]
    assert api.preferences()["verification_status"] == "failed"


def test_a_resend_whose_subscription_is_deleted_while_its_email_goes_out_answers_409(
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The email went out, but the subscription is gone, so there are no settings to return."""
    _failed_verification(api)

    def answer(_email: OutgoingEmail) -> SendOutcome:
        with api.session() as db:
            db.execute(
                delete(AlertSubscription).where(
                    AlertSubscription.investor_id == api.investor.id
                )
            )
            db.commit()
        return Accepted("recorded-1")

    sender = RecordingEmailSender(answer)
    _send_with(monkeypatch, sender)

    response = api.client.post("/notifications/preferences/resend-verification")

    assert (response.status_code, response.json()) == (
        409,
        {"detail": "Notification preferences changed concurrently"},
    )
    assert [email.to for email in sender.sent] == [api.investor.email]
