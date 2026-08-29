"""Contracts for the Brevo transactional-email boundary."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.core.config import settings
from app.services import brevo_alerts


RECIPIENT = "investor@example.com"
UNSUBSCRIBE_URL = "https://app.example.test/unsubscribe/?t=signed"


@pytest.fixture(autouse=True)
def _reset_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", "alerts@example.com", raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_NAME", "Stocks In Hand", raising=False)
    monkeypatch.setattr(settings, "BREVO_API_KEY", "test-api-key", raising=False)
    monkeypatch.setattr(
        settings,
        "BREVO_API_BASE_URL",
        "https://api.brevo.com/v3",
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED",
        True,
        raising=False,
    )
    brevo_alerts._client.cache_clear()  # pylint: disable=protected-access


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.Client:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(brevo_alerts, "_client", lambda: client)
    return client


def test_send_email_posts_brevo_transactional_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live delivery must send both bodies and unsubscribe headers."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("api-key")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(201, json={"messageId": "brevo-message-1"})

    client = _install_transport(monkeypatch, handler)
    try:
        message_id = brevo_alerts.send_email(
            to=RECIPIENT,
            subject="BHP watchlist alert",
            html="<p>html</p>",
            text="plain text",
            unsubscribe_url=UNSUBSCRIBE_URL,
        )
    finally:
        client.close()
    assert message_id == "brevo-message-1"
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["api_key"] == "test-api-key"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["sender"] == {
        "email": "alerts@example.com",
        "name": "Stocks In Hand",
    }
    assert payload["to"] == [{"email": RECIPIENT}]
    assert payload["htmlContent"] == "<p>html</p>"
    assert payload["textContent"] == "plain text"
    assert payload["headers"] == {
        "List-Unsubscribe": f"<{UNSUBSCRIBE_URL}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def test_confirmation_email_omits_unsubscribe_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmation message must not contain a one-click unsubscribe header."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"messageId": "verification-message"})

    client = _install_transport(monkeypatch, handler)
    try:
        brevo_alerts.send_email(
            to=RECIPIENT,
            subject="Confirm alerts",
            html="<p>confirm</p>",
            text="confirm",
        )
    finally:
        client.close()

    assert "headers" not in captured


def test_dry_run_is_stable_and_does_not_create_a_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry-run delivery must remain deterministic and network-free."""
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", True, raising=False)
    client = pytest.MonkeyPatch()
    client.setattr(
        brevo_alerts,
        "_client",
        lambda: pytest.fail("client must not be created"),
    )
    try:
        arguments = {
            "to": RECIPIENT,
            "subject": "Alert",
            "html": "<p>html</p>",
            "text": "plain",
            "unsubscribe_url": "http://localhost:3000/unsubscribe/?t=signed",
        }
        first = brevo_alerts.send_email(**arguments)
        second = brevo_alerts.send_email(**arguments)
    finally:
        client.undo()

    assert first == second
    assert first.startswith("dry-run-")


@pytest.mark.parametrize("field", ["ALERT_SENDER_EMAIL", "BREVO_API_KEY"])
def test_live_send_requires_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    """Live delivery must fail closed when a provider value is missing."""
    monkeypatch.setattr(settings, field, "", raising=False)

    with pytest.raises(brevo_alerts.BrevoAlertConfigurationError):
        brevo_alerts.send_email(
            to=RECIPIENT,
            subject="Alert",
            html="<p>html</p>",
            text="plain",
            unsubscribe_url=UNSUBSCRIBE_URL,
        )


def test_live_send_requires_https_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live provider and unsubscribe URLs must use encrypted transport."""
    with pytest.raises(ValueError, match="unsubscribe_url must use HTTPS"):
        brevo_alerts.send_email(
            to=RECIPIENT,
            subject="Alert",
            html="<p>html</p>",
            text="plain",
            unsubscribe_url="http://app.example.test/unsubscribe/?t=signed",
        )

    monkeypatch.setattr(
        settings,
        "BREVO_API_BASE_URL",
        "http://api.example.test/v3",
        raising=False,
    )
    with pytest.raises(brevo_alerts.BrevoAlertConfigurationError):
        brevo_alerts.send_email(
            to=RECIPIENT,
            subject="Alert",
            html="<p>html</p>",
            text="plain",
            unsubscribe_url=UNSUBSCRIBE_URL,
        )


@pytest.mark.parametrize(
    ("recipient", "subject"),
    [
        ("not-an-email", "Alert"),
        (RECIPIENT, "Alert\r\nBcc: attacker@example.com"),
    ],
)
def test_send_rejects_invalid_mailboxes_and_header_injection(
    recipient: str,
    subject: str,
) -> None:
    """Invalid recipients and injected subject headers must be rejected."""
    with pytest.raises(ValueError):
        brevo_alerts.send_email(
            to=recipient,
            subject=subject,
            html="<p>html</p>",
            text="plain",
            unsubscribe_url=UNSUBSCRIBE_URL,
        )


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(400, False), (401, False), (429, True), (503, True)],
)
def test_api_errors_are_sanitized_and_classified(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    retryable: bool,
) -> None:
    """Provider failures must expose only a safe code and retry decision."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"code": "invalid_parameter", "message": "secret detail"},
        )

    client = _install_transport(monkeypatch, handler)
    try:
        with pytest.raises(brevo_alerts.BrevoApiError) as raised:
            brevo_alerts.send_email(
                to=RECIPIENT,
                subject="Alert",
                html="<p>html</p>",
                text="plain",
                unsubscribe_url=UNSUBSCRIBE_URL,
            )
    finally:
        client.close()

    assert raised.value.status_code == status_code
    assert raised.value.code == "invalid_parameter"
    assert raised.value.retryable is retryable
    assert "secret detail" not in str(raised.value)


def test_success_response_requires_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A success response without a delivery identifier is incomplete."""
    client = _install_transport(
        monkeypatch,
        lambda _request: httpx.Response(201, json={}),
    )
    try:
        with pytest.raises(RuntimeError, match="messageId"):
            brevo_alerts.send_email(
                to=RECIPIENT,
                subject="Alert",
                html="<p>html</p>",
                text="plain",
                unsubscribe_url=UNSUBSCRIBE_URL,
            )
    finally:
        client.close()
