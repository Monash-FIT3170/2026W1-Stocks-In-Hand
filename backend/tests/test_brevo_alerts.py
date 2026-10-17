"""The Brevo adapter behind the email sender interface.

Each test gives the adapter an httpx mock transport in place of Brevo, so
nothing is patched.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest

from app.services.brevo_alerts import BrevoEmailSender
from app.services.email_sender import (
    Accepted,
    Misconfigured,
    OutgoingEmail,
    RecipientRejected,
    SendOutcome,
    SendPacer,
    Unavailable,
)


RECIPIENT = "investor@example.com"
UNSUBSCRIBE_URL = "https://app.example.test/unsubscribe/?t=signed"
ALERT = OutgoingEmail(
    to=RECIPIENT,
    subject="BHP watchlist alert",
    html="<p>html</p>",
    text="plain text",
    unsubscribe_url=UNSUBSCRIBE_URL,
)
BREVO_REJECTED = "Brevo rejected the recipient or message"


def _brevo(
    handler: Callable[[httpx.Request], httpx.Response],
    **overrides: object,
) -> BrevoEmailSender:
    """A Brevo sender whose requests reach ``handler`` instead of Brevo."""
    values: dict[str, object] = {
        "api_key": "test-api-key",
        "sender_email": "alerts@example.com",
        "sender_name": "Stocks In Hand",
        "base_url": "https://api.brevo.com/v3",
        "client": httpx.Client(transport=httpx.MockTransport(handler)),
    }
    values.update(overrides)
    return BrevoEmailSender(**values)  # type: ignore[arg-type]


def _accepted(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, json={"messageId": "brevo-message-1"})


def _no_request(_request: httpx.Request) -> httpx.Response:
    pytest.fail("Brevo must not be called")


def test_brevo_sender_posts_one_transactional_email() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _accepted(request)

    assert _brevo(handler).send(ALERT) == Accepted("brevo-message-1")
    assert str(requests[0].url) == "https://api.brevo.com/v3/smtp/email"
    assert requests[0].headers["api-key"] == "test-api-key"
    assert json.loads(requests[0].content) == {
        "sender": {"email": "alerts@example.com", "name": "Stocks In Hand"},
        "to": [{"email": RECIPIENT}],
        "subject": "BHP watchlist alert",
        "htmlContent": "<p>html</p>",
        "textContent": "plain text",
        # The unsubscribe page is served by CloudFront from S3 and allows only
        # GET, so the message must not invite a one-click POST to it.
        "headers": {"List-Unsubscribe": f"<{UNSUBSCRIBE_URL}>"},
    }


def test_brevo_sender_adds_no_headers_without_an_unsubscribe_link() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return _accepted(request)

    _brevo(handler).send(replace(ALERT, unsubscribe_url=None))

    assert "headers" not in payloads[0]


@pytest.mark.parametrize(
    ("status_code", "code", "outcome"),
    [
        (400, "invalid_parameter", RecipientRejected("invalid_parameter", BREVO_REJECTED)),
        (404, "document_not_found", RecipientRejected("document_not_found", BREVO_REJECTED)),
        (422, "invalid_parameter", RecipientRejected("invalid_parameter", BREVO_REJECTED)),
        (401, "unauthorized", Misconfigured("unauthorized")),
        (402, "not_enough_credits", Misconfigured("not_enough_credits")),
        (403, "permission_denied", Misconfigured("permission_denied")),
        (408, "timeout", Unavailable("timeout")),
        (429, "too_many_requests", Unavailable("too_many_requests")),
        (503, "service_unavailable", Unavailable("service_unavailable")),
    ],
)
def test_a_brevo_refusal_becomes_an_outcome_without_its_message(
    status_code: int,
    code: str,
    outcome: SendOutcome,
) -> None:
    sender = _brevo(
        lambda _request: httpx.Response(
            status_code,
            json={"code": code, "message": "secret detail"},
        )
    )

    result = sender.send(ALERT)

    assert result == outcome
    assert "secret detail" not in repr(result)


def test_a_brevo_refusal_without_a_code_is_named_by_its_status() -> None:
    sender = _brevo(lambda _request: httpx.Response(503, text="Service Unavailable"))

    assert sender.send(ALERT) == Unavailable("brevo_http_503")


def test_a_network_failure_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert _brevo(handler).send(ALERT) == Unavailable("brevo_transport_error")


@pytest.mark.parametrize(
    "response",
    [httpx.Response(201, json={}), httpx.Response(201, text="not json")],
)
def test_a_success_without_a_message_id_is_unavailable(
    response: httpx.Response,
) -> None:
    assert _brevo(lambda _request: response).send(ALERT) == Unavailable(
        "brevo_send_failed"
    )


@pytest.mark.parametrize(
    ("overrides", "email", "outcome"),
    [
        ({"api_key": " "}, ALERT, Misconfigured("brevo_configuration_error")),
        ({"sender_email": ""}, ALERT, Misconfigured("brevo_configuration_error")),
        (
            {"base_url": "http://api.example.test/v3"},
            ALERT,
            Misconfigured("brevo_configuration_error"),
        ),
        ({"base_url": ""}, ALERT, Misconfigured("invalid_notification_configuration")),
        (
            {"base_url": "api.brevo.com/v3"},
            ALERT,
            Misconfigured("invalid_notification_configuration"),
        ),
        (
            {"base_url": "https://api.brevo.com/v3<x>"},
            ALERT,
            Misconfigured("invalid_notification_configuration"),
        ),
        (
            {"base_url": "https://api.brevo.com/v3\r\nX-Extra: 1"},
            ALERT,
            Misconfigured("invalid_notification_configuration"),
        ),
        (
            {"base_url": "https://[api.brevo.com/v3"},
            ALERT,
            Misconfigured("invalid_notification_configuration"),
        ),
        (
            {"sender_email": "not-an-email"},
            ALERT,
            Misconfigured("invalid_notification_configuration"),
        ),
        (
            {"sender_name": " "},
            ALERT,
            Misconfigured("invalid_notification_configuration"),
        ),
        (
            {},
            replace(ALERT, unsubscribe_url="http://app.example.test/unsubscribe/?t=x"),
            Misconfigured("invalid_notification_configuration"),
        ),
        (
            {},
            replace(ALERT, to="not-an-email"),
            RecipientRejected("invalid_recipient", "Recipient address is invalid"),
        ),
    ],
)
def test_brevo_sender_checks_its_settings_and_the_email_before_any_request(
    overrides: dict[str, object],
    email: OutgoingEmail,
    outcome: SendOutcome,
) -> None:
    assert _brevo(_no_request, **overrides).send(email) == outcome


def test_a_paced_brevo_sender_waits_out_the_interval_before_posting() -> None:
    times = iter([10.0, 10.25, 11.25])
    sleeps: list[float] = []
    pacer = SendPacer(1.0, clock=lambda: next(times), sleep=sleeps.append)
    sender = _brevo(_accepted, pacer=pacer)

    sender.send(ALERT)
    sender.send(ALERT)

    assert sleeps == [0.75]
