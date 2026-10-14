"""The alert subscription routes, on Postgres with a fake email sender.

Each test signs in a fresh investor and calls the notification routes through
the FastAPI app. Every database session a request opens is a savepoint inside
one transaction that the test rolls back, and a RecordingEmailSender stands
in for Brevo.
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import main
from app.api.deps import get_current_investor
from app.core.config import settings
from app.database.connection import get_db
from app.models.alert_rule import AlertRule
from app.models.alert_subscription import AlertSubscription
from app.models.investor import Investor
from app.services import email_sender
from app.services.email_sender import (
    EmailSender,
    Misconfigured,
    OutgoingEmail,
    RecipientRejected,
    RecordingEmailSender,
    Unavailable,
)

ENABLE_ALERTS = {
    "enabled": True,
    "sentiment_labels": ["negative"],
    "min_confidence": 0.75,
}


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
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    engine = create_engine(settings.DATABASE_URL)
    try:
        with engine.connect() as probe:
            if not inspect(probe).has_table("alert_subscriptions"):
                engine.dispose()
                pytest.skip("Alert migrations are not applied")
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL is unavailable: {exc}")
    connection = engine.connect()
    outer = connection.begin()

    @contextmanager
    def session() -> Iterator[Session]:
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            db.close()

    def request_session() -> Iterator[Session]:
        with session() as db:
            yield db

    email = f"alert-subscription-{uuid.uuid4().hex}@example.com"
    with session() as db:
        investor = Investor(email=email, username="Alert subscription test")
        db.add(investor)
        db.flush()
        account = SimpleNamespace(id=investor.id, email=email)
        db.commit()

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
        outer.rollback()
        connection.close()
        engine.dispose()


def _send_with(monkeypatch: pytest.MonkeyPatch, sender: EmailSender) -> None:
    monkeypatch.setattr(email_sender, "configured_sender", lambda **_: sender)


def _verification_token(email: OutgoingEmail) -> str:
    link = next(
        line for line in email.text.splitlines() if "/verify-notifications/" in line
    )
    assert link.startswith("https://app.example.test/verify-notifications/?t=")
    return parse_qs(urlsplit(link).query)["t"][0]


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
                    unsubscribe_token_hash="a" * 64,
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

    verified = api.client.post(
        "/notifications/verify",
        json={"token": _verification_token(sender.sent[0])},
    )

    assert verified.status_code == 200
    assert api.preferences()["verification_status"] == "verified"


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
