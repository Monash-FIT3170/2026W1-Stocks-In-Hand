"""Contracts for notification preference and unsubscribe routes."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.api.deps import get_current_investor
from app.api.routes import notification_preferences as routes
from app.core.config import settings
from app.schemas.notification import (
    NotificationPreferencesUpdate,
    UnsubscribeRequest,
    VerificationRequest,
)
from app.services.unsubscribe_tokens import create_signed_unsubscribe_token
from app.services.verification_tokens import create_signed_verification_token


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _investor():
    return SimpleNamespace(
        id=uuid4(),
        email="investor@example.com",
    )


def _subscription(**overrides):
    values = {
        "id": uuid4(),
        "investor_id": uuid4(),
        "email": "investor@example.com",
        "enabled": True,
        "verification_status": "pending",
        "verification_requested_at": datetime.now(timezone.utc),
        "verified_at": None,
        "last_delivery_status": None,
        "last_delivery_error_code": None,
        "last_delivery_at": None,
        "unsubscribe_token_hash": "a" * 64,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _rule(**overrides):
    values = {
        "enabled": True,
        "sentiment_labels": ["negative"],
        "min_confidence": 0.75,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def _enable_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True, raising=False)


def test_notification_schema_rejects_duplicate_labels_and_bad_confidence() -> None:
    """Invalid rule preferences must fail before reaching persistence."""
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


def test_get_preferences_returns_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new investor should receive disabled, negative-only defaults."""
    investor = _investor()
    monkeypatch.setattr(routes, "_load_preferences", lambda *_args: (None, None))

    response = routes.get_notification_preferences(
        db=MagicMock(),
        current_investor=investor,
    )

    assert response.feature_enabled is True
    assert response.enabled is False
    assert str(response.email) == investor.email
    assert response.sentiment_labels == ["negative"]
    assert response.min_confidence == pytest.approx(0.75)
    assert response.verification_status == "unverified"
    assert response.unsubscribe_token is None


def test_get_preferences_keeps_pending_local_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET must not ask an external provider for recipient identity state."""
    investor = _investor()
    pending = _subscription(investor_id=investor.id)
    rule = _rule()
    monkeypatch.setattr(routes, "_load_preferences", lambda *_args: (pending, rule))

    response = routes.get_notification_preferences(
        db=MagicMock(),
        current_investor=investor,
    )

    assert response.verification_status == "pending"


def test_verification_email_contains_current_signed_app_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider message must link back to the app with a valid token."""
    subscription_id = uuid4()
    requested_at = datetime.now(timezone.utc)
    token_hash = "d" * 64
    send = MagicMock(return_value="brevo-verification-message")
    monkeypatch.setattr(
        settings,
        "FRONTEND_BASE_URL",
        "https://app.example.test",
        raising=False,
    )
    monkeypatch.setattr(routes.brevo_alerts, "send_email", send)

    routes._send_verification_email(  # pylint: disable=protected-access
        subscription_id=subscription_id,
        email="investor@example.com",
        unsubscribe_token_hash=token_hash,
        requested_at=requested_at,
    )

    text_body = send.call_args.kwargs["text"]
    token = text_body.split("?t=", 1)[1].splitlines()[0]
    assert send.call_args.kwargs["to"] == "investor@example.com"
    assert "/verify-notifications/?t=" in text_body
    assert routes.verify_signed_verification_token(
        token,
        token_hash,
        requested_at,
        now=requested_at,
        ttl=timedelta(hours=24),
    ) == subscription_id


def test_enable_preferences_returns_raw_token_once_and_stores_only_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First enable returns the raw secret while persisting only SHA-256."""
    investor = _investor()
    db = MagicMock()
    pending = _subscription(
        investor_id=investor.id,
        unsubscribe_token_hash=None,
    )
    rule = _rule(sentiment_labels=["negative", "positive"], min_confidence=0.8)
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "get_subscription_by_investor",
        lambda *_args: None,
    )
    verification = MagicMock()
    monkeypatch.setattr(routes, "_send_verification_email", verification)

    subscription_upsert = MagicMock(return_value=pending)
    rule_upsert = MagicMock(return_value=rule)
    state_update = MagicMock(return_value=pending)
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "upsert_subscription",
        subscription_upsert,
    )
    monkeypatch.setattr(
        routes.alert_rule_crud,
        "upsert_default_alert_rule",
        rule_upsert,
    )
    monkeypatch.setattr(routes, "_load_preferences", lambda *_args: (pending, rule))
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "update_verification_state",
        state_update,
    )

    response = routes.update_notification_preferences(
        body=NotificationPreferencesUpdate(
            enabled=True,
            min_confidence=0.8,
            sentiment_labels=["negative", "positive"],
        ),
        db=db,
        current_investor=investor,
    )

    assert response.unsubscribe_token is not None
    expected_hash = hashlib.sha256(
        response.unsubscribe_token.encode("utf-8")
    ).hexdigest()
    assert subscription_upsert.call_args.kwargs["unsubscribe_token_hash"] == (
        expected_hash
    )
    assert response.unsubscribe_token != expected_hash
    verification.assert_called_once()
    assert verification.call_args.kwargs["email"] == investor.email
    db.commit.assert_called_once()


def test_enable_is_blocked_while_deployment_switch_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The master switch must block verification and preference activation."""
    investor = _investor()
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False, raising=False)
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "get_subscription_by_investor",
        lambda *_args: None,
    )
    verification = MagicMock()
    monkeypatch.setattr(routes, "_send_verification_email", verification)

    with pytest.raises(HTTPException) as error:
        routes.update_notification_preferences(
            body=NotificationPreferencesUpdate(enabled=True),
            db=MagicMock(),
            current_investor=investor,
        )

    assert error.value.status_code == 503
    verification.assert_not_called()


def test_resend_verification_is_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second verification request within one minute must return 429."""
    investor = _investor()
    subscription = _subscription(
        investor_id=investor.id,
        verification_requested_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        routes,
        "_load_preferences",
        lambda *_args: (subscription, _rule()),
    )
    verification = MagicMock()
    monkeypatch.setattr(routes, "_send_verification_email", verification)

    with pytest.raises(HTTPException) as error:
        routes.resend_notification_verification(
            db=MagicMock(),
            current_investor=investor,
        )

    assert error.value.status_code == 429
    assert 1 <= int(error.value.headers["Retry-After"]) <= 60
    verification.assert_not_called()


def test_saving_preferences_cannot_bypass_verification_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated preference saves must not send extra confirmation emails."""
    investor = _investor()
    subscription = _subscription(
        investor_id=investor.id,
        verification_requested_at=datetime.now(timezone.utc),
    )
    rule = _rule()
    db = MagicMock()
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "get_subscription_by_investor",
        lambda *_args: subscription,
    )
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "upsert_subscription",
        lambda *_args, **_kwargs: subscription,
    )
    monkeypatch.setattr(
        routes.alert_rule_crud,
        "upsert_default_alert_rule",
        lambda *_args, **_kwargs: rule,
    )
    verification = MagicMock()
    monkeypatch.setattr(routes, "_send_verification_email", verification)

    response = routes.update_notification_preferences(
        body=NotificationPreferencesUpdate(enabled=True),
        db=db,
        current_investor=investor,
    )

    assert response.verification_status == "pending"
    verification.assert_not_called()


def test_resend_reserves_database_window_before_brevo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The persisted rate-limit reservation must precede the Brevo request."""
    investor = _investor()
    subscription = _subscription(
        investor_id=investor.id,
        verification_status="failed",
        verification_requested_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    rule = _rule()
    events: list[str] = []
    db = MagicMock()
    db.rollback.side_effect = lambda: events.append("transaction_released")
    monkeypatch.setattr(
        routes,
        "_load_preferences",
        lambda *_args: (subscription, rule),
    )

    def reserve(*_args, **_kwargs):
        events.append("reserved")
        subscription.verification_status = "pending"
        return subscription

    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "update_verification_state",
        reserve,
    )
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "get_subscription",
        lambda *_args: subscription,
    )
    monkeypatch.setattr(
        routes,
        "_send_verification_email",
        lambda **_kwargs: events.append("brevo_requested"),
    )

    response = routes.resend_notification_verification(
        db=db,
        current_investor=investor,
    )

    assert response.verification_status == "pending"
    assert events == ["reserved", "transaction_released", "brevo_requested"]


def test_signed_verification_token_confirms_pending_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A current signed link must complete the guarded local confirmation."""
    requested_at = datetime.now(timezone.utc)
    pending = _subscription(verification_requested_at=requested_at)
    token = create_signed_verification_token(
        pending.id,
        pending.unsubscribe_token_hash,
        requested_at,
    )
    verified = _subscription(
        id=pending.id,
        investor_id=pending.investor_id,
        verification_status="verified",
        verification_requested_at=requested_at,
        verified_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "get_subscription",
        lambda *_args: pending,
    )
    update = MagicMock(return_value=verified)
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "update_verification_state",
        update,
    )

    response = routes.verify_notification_email(
        VerificationRequest(token=token),
        db=MagicMock(),
    )

    assert response.message == routes.VERIFICATION_MESSAGE
    assert update.call_args.kwargs["verification_status"] == "verified"
    assert update.call_args.kwargs["expected_verification_status"] == "pending"
    assert update.call_args.kwargs["expected_verification_requested_at"] == (
        requested_at
    )


def test_expired_verification_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expired links must not change subscription confirmation state."""
    requested_at = datetime.now(timezone.utc) - timedelta(hours=25)
    pending = _subscription(verification_requested_at=requested_at)
    token = create_signed_verification_token(
        pending.id,
        pending.unsubscribe_token_hash,
        requested_at,
    )
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "get_subscription",
        lambda *_args: pending,
    )
    update = MagicMock()
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "update_verification_state",
        update,
    )

    with pytest.raises(HTTPException) as error:
        routes.verify_notification_email(
            VerificationRequest(token=token),
            db=MagicMock(),
        )

    assert error.value.status_code == 400
    update.assert_not_called()


def test_raw_and_signed_unsubscribe_tokens_disable_without_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both token forms disable while every result returns identical text."""
    db = MagicMock()
    raw_token = "raw-unsubscribe-token-value-1234567890"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    raw_subscription = _subscription(unsubscribe_token_hash=token_hash)
    signed_subscription = _subscription(unsubscribe_token_hash="b" * 64)
    signed_token = create_signed_unsubscribe_token(
        signed_subscription.id,
        signed_subscription.unsubscribe_token_hash,
    )
    disable = MagicMock()
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "get_subscription_by_unsubscribe_token_hash",
        lambda _db, value: raw_subscription if value == token_hash else None,
    )
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "get_subscription",
        lambda _db, value: signed_subscription
        if value == signed_subscription.id
        else None,
    )
    monkeypatch.setattr(
        routes.alert_subscription_crud,
        "disable_subscription",
        disable,
    )

    first = routes.unsubscribe_notifications(
        UnsubscribeRequest(token=raw_token),
        db=db,
    )
    second = routes.unsubscribe_notifications(
        UnsubscribeRequest(token=signed_token),
        db=db,
    )
    invalid = routes.unsubscribe_notifications(
        UnsubscribeRequest(token="invalid-token-value-123456"),
        db=db,
    )

    assert first.message == routes.UNSUBSCRIBE_MESSAGE
    assert second.message == routes.UNSUBSCRIBE_MESSAGE
    assert invalid.message == routes.UNSUBSCRIBE_MESSAGE
    assert disable.call_count == 2


def test_router_authenticates_preferences_but_not_public_token_routes() -> None:
    """Preference routes require a session while token callbacks stay public."""
    notification_routes = [
        route
        for route in routes.router.routes
        if isinstance(route, APIRoute) and route.path.startswith("/notifications")
    ]

    assert {route.path for route in notification_routes} == {
        "/notifications/preferences",
        "/notifications/preferences/resend-verification",
        "/notifications/verify",
        "/notifications/unsubscribe",
    }
    preference_routes = [
        route
        for route in notification_routes
        if route.path
        not in {"/notifications/unsubscribe", "/notifications/verify"}
    ]
    assert len(preference_routes) == 3
    for route in preference_routes:
        dependencies = {
            dependency.call for dependency in route.dependant.dependencies
        }
        assert get_current_investor in dependencies

    unsubscribe_route = next(
        route
        for route in notification_routes
        if route.path == "/notifications/unsubscribe"
    )
    unsubscribe_dependencies = {
        dependency.call
        for dependency in unsubscribe_route.dependant.dependencies
    }
    assert get_current_investor not in unsubscribe_dependencies

    verification_route = next(
        route
        for route in notification_routes
        if route.path == "/notifications/verify"
    )
    verification_dependencies = {
        dependency.call
        for dependency in verification_route.dependant.dependencies
    }
    assert get_current_investor not in verification_dependencies

    main_module = (REPOSITORY_ROOT / "backend" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "notification_preferences," in main_module
