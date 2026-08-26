"""Unit tests for the SES alert service and email templates.

These tests stub the SES client boundary directly. They must never need AWS,
LocalStack, or a network connection.
"""

# pylint: disable=protected-access,wrong-import-position

import logging
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services import ses_alerts
from app.services.alert_templates import render_alert_email


RECIPIENT = "investor@monash.edu"
SENDER = "alerts@stocksinhand.com.au"
UNSUBSCRIBE_URL = (
    "https://api.stocksinhand.com.au/api/notifications/"
    "unsubscribe?t=signed-token"
)


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": f"{code} from SES"}}, operation
    )


def test_client_uses_sesv2_region_and_optional_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cached client should use the configured SESv2 endpoint and region."""
    client = MagicMock()
    client_factory = MagicMock(return_value=client)
    monkeypatch.setattr(ses_alerts.boto3, "client", client_factory)
    monkeypatch.setattr(settings, "AWS_REGION", "ap-southeast-2", raising=False)
    monkeypatch.setattr(
        settings,
        "AWS_ENDPOINT_URL_SES",
        "http://localhost:4566",
        raising=False,
    )
    ses_alerts._client.cache_clear()

    try:
        assert ses_alerts._client() is client
        client_factory.assert_called_once_with(
            "sesv2",
            region_name="ap-southeast-2",
            endpoint_url="http://localhost:4566",
        )
    finally:
        ses_alerts._client.cache_clear()


def test_dry_run_send_never_calls_ses_or_logs_sensitive_email_content(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Dry-run delivery must remain local and keep private content out of logs."""
    client = MagicMock()
    recipient = "private.recipient@monash.edu"
    html = "<p>Private alert body</p>"
    unsubscribe_url = (
        "https://api.stocksinhand.com.au/api/notifications/"
        "unsubscribe?t=super-secret-token"
    )
    monkeypatch.setattr(ses_alerts, "_client", client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", True, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", SENDER, raising=False)
    caplog.set_level(logging.DEBUG)

    message_id = ses_alerts.send_alert(
        recipient,
        "Private alert subject",
        html,
        "Private alert body",
        unsubscribe_url,
    )

    assert isinstance(message_id, str)
    assert message_id
    client.assert_not_called()
    assert recipient not in caplog.text
    assert html not in caplog.text
    assert "Private alert body" not in caplog.text
    assert "Private alert subject" not in caplog.text
    assert "super-secret-token" not in caplog.text

    repeated_message_id = ses_alerts.send_alert(
        recipient,
        "Private alert subject",
        html,
        "Private alert body",
        unsubscribe_url,
    )
    assert repeated_message_id == message_id


def test_dry_run_identity_actions_never_create_an_ses_client(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Dry-run verification and status checks must not construct an SES client."""
    client_factory = MagicMock()
    email = "private.investor@monash.edu"
    monkeypatch.setattr(ses_alerts, "_client", client_factory)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", True, raising=False)
    caplog.set_level(logging.DEBUG)

    ses_alerts.request_verification(email)
    assert ses_alerts.identity_status(email) == "pending"

    client_factory.assert_not_called()
    assert email not in caplog.text


def test_request_verification_creates_email_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verification should create the exact recipient identity."""
    client = MagicMock()
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)

    ses_alerts.request_verification(RECIPIENT)
    client.create_email_identity.assert_called_once_with(
        EmailIdentity=RECIPIENT
    )


def test_request_verification_treats_existing_identity_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing SES identity should be treated as an idempotent success."""
    client = MagicMock()
    client.create_email_identity.side_effect = _client_error(
        "AlreadyExistsException", "CreateEmailIdentity"
    )
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)

    ses_alerts.request_verification(RECIPIENT)
    client.create_email_identity.assert_called_once_with(
        EmailIdentity=RECIPIENT
    )


def test_request_verification_propagates_unexpected_ses_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected verification failures must remain visible to the caller."""
    client = MagicMock()
    error = _client_error("AccessDeniedException", "CreateEmailIdentity")
    client.create_email_identity.side_effect = error
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)

    with pytest.raises(ClientError) as raised:
        ses_alerts.request_verification(RECIPIENT)

    assert raised.value is error


@pytest.mark.parametrize(
    ("ses_response", "expected"),
    [
        ({"VerifiedForSendingStatus": True}, "verified"),
        ({"VerifiedForSendingStatus": False}, "pending"),
        (
            {
                "VerifiedForSendingStatus": False,
                "VerificationStatus": "FAILED",
            },
            "failed",
        ),
        (
            {
                "VerifiedForSendingStatus": False,
                "VerificationStatus": "TEMPORARY_FAILURE",
            },
            "pending",
        ),
        (
            {
                "VerifiedForSendingStatus": False,
                "VerificationStatus": "NOT_STARTED",
            },
            "unverified",
        ),
    ],
)
def test_identity_status_maps_ses_verification_state(
    monkeypatch: pytest.MonkeyPatch,
    ses_response: dict[str, object],
    expected: str,
) -> None:
    """SES verification fields should map to the local status vocabulary."""
    client = MagicMock()
    client.get_email_identity.return_value = ses_response
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)

    assert ses_alerts.identity_status(RECIPIENT) == expected
    client.get_email_identity.assert_called_once_with(
        EmailIdentity=RECIPIENT
    )


def test_identity_status_maps_missing_identity_to_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing SES identity should map to the unverified state."""
    client = MagicMock()
    client.get_email_identity.side_effect = _client_error(
        "NotFoundException", "GetEmailIdentity"
    )
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)

    assert ses_alerts.identity_status(RECIPIENT) == "unverified"


def test_identity_status_propagates_non_missing_ses_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status checks must not hide unexpected SES failures."""
    client = MagicMock()
    error = _client_error("AccessDeniedException", "GetEmailIdentity")
    client.get_email_identity.side_effect = error
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)

    with pytest.raises(ClientError) as raised:
        ses_alerts.identity_status(RECIPIENT)

    assert raised.value is error


def test_send_alert_uses_raw_multipart_mime_and_unsubscribe_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live delivery should send raw multipart MIME with unsubscribe headers."""
    client = MagicMock()
    client.send_email.return_value = {"MessageId": "ses-message-123"}
    unsubscribe_url = UNSUBSCRIBE_URL
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", SENDER, raising=False)
    monkeypatch.setattr(
        settings,
        "ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED",
        True,
        raising=False,
    )

    message_id = ses_alerts.send_alert(
        RECIPIENT,
        "BHP negative news alert",
        "<p><strong>BHP</strong> outlook declined.</p>",
        "BHP outlook declined.",
        unsubscribe_url,
    )

    assert message_id == "ses-message-123"
    client.send_email.assert_called_once()
    kwargs = client.send_email.call_args.kwargs
    assert kwargs["FromEmailAddress"] == SENDER
    assert kwargs["Destination"] == {"ToAddresses": [RECIPIENT]}
    raw_message = kwargs["Content"]["Raw"]["Data"]
    parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
    assert parsed["To"] == RECIPIENT
    assert parsed["From"] == SENDER
    assert parsed["Subject"] == "BHP negative news alert"
    assert parsed["List-Unsubscribe"] == f"<{unsubscribe_url}>"
    assert parsed["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert parsed.get_content_type() == "multipart/alternative"
    plain_part = parsed.get_body(preferencelist=("plain",))
    html_part = parsed.get_body(preferencelist=("html",))
    assert plain_part is not None
    assert html_part is not None
    assert plain_part.get_content().strip() == "BHP outlook declined."
    assert "<strong>BHP</strong>" in html_part.get_content()


def test_send_alert_omits_one_click_header_when_feature_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary unsubscribe remains while RFC 8058 support is disabled."""
    client = MagicMock()
    client.send_email.return_value = {"MessageId": "ses-message-124"}
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", SENDER, raising=False)
    monkeypatch.setattr(
        settings,
        "ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED",
        False,
        raising=False,
    )

    ses_alerts.send_alert(
        RECIPIENT,
        "BHP alert",
        "<p>HTML</p>",
        "Text",
        UNSUBSCRIBE_URL,
    )

    raw_message = client.send_email.call_args.kwargs["Content"]["Raw"]["Data"]
    parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
    assert parsed["List-Unsubscribe"] == f"<{UNSUBSCRIBE_URL}>"
    assert parsed["List-Unsubscribe-Post"] is None


def test_send_alert_requires_sender_in_live_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live delivery should fail clearly when no sender is configured."""
    client = MagicMock()
    monkeypatch.setattr(ses_alerts, "_client", client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", "", raising=False)

    with pytest.raises(ValueError, match="ALERT_SENDER_EMAIL"):
        ses_alerts.send_alert(
            RECIPIENT,
            "Subject",
            "<p>HTML</p>",
            "Text",
            UNSUBSCRIBE_URL,
        )

    client.assert_not_called()


def test_send_alert_rejects_http_unsubscribe_url_in_live_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live email headers must use an HTTPS unsubscribe URL."""
    client = MagicMock()
    monkeypatch.setattr(ses_alerts, "_client", client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", SENDER, raising=False)

    with pytest.raises(ValueError, match="must use HTTPS"):
        ses_alerts.send_alert(
            RECIPIENT,
            "Subject",
            "<p>HTML</p>",
            "Text",
            "http://localhost:3000/unsubscribe?t=token",
        )

    client.assert_not_called()


@pytest.mark.parametrize(
    "recipient",
    [
        "not-an-email",
        "Investor <investor@monash.edu>",
        "first@monash.edu,second@monash.edu",
        "pelé@monash.edu",
    ],
)
def test_send_alert_rejects_invalid_or_unsupported_recipient_mailboxes(
    monkeypatch: pytest.MonkeyPatch,
    recipient: str,
) -> None:
    """The service should accept one ASCII mailbox without a display name."""
    client = MagicMock()
    monkeypatch.setattr(ses_alerts, "_client", client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", SENDER, raising=False)

    with pytest.raises(ValueError, match="one valid email address"):
        ses_alerts.send_alert(
            recipient,
            "Subject",
            "<p>HTML</p>",
            "Text",
            UNSUBSCRIBE_URL,
        )

    client.assert_not_called()


def test_send_alert_rejects_invalid_sender_mailbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured display name must not become an ambiguous SES sender."""
    client = MagicMock()
    monkeypatch.setattr(ses_alerts, "_client", client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(
        settings,
        "ALERT_SENDER_EMAIL",
        "Stocks In Hand <alerts@stocksinhand.com.au>",
        raising=False,
    )

    with pytest.raises(ValueError, match="one valid email address"):
        ses_alerts.send_alert(
            RECIPIENT,
            "Subject",
            "<p>HTML</p>",
            "Text",
            UNSUBSCRIBE_URL,
        )

    client.assert_not_called()


def test_send_alert_requires_ses_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful-looking SES response must include its message ID."""
    client = MagicMock()
    client.send_email.return_value = {}
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", SENDER, raising=False)

    with pytest.raises(RuntimeError, match="did not include MessageId"):
        ses_alerts.send_alert(
            RECIPIENT,
            "Subject",
            "<p>HTML</p>",
            "Text",
            UNSUBSCRIBE_URL,
        )


def test_send_alert_propagates_ses_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected send failures must remain visible to the caller."""
    client = MagicMock()
    error = _client_error("AccessDeniedException", "SendEmail")
    client.send_email.side_effect = error
    monkeypatch.setattr(ses_alerts, "_client", lambda: client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", SENDER, raising=False)

    with pytest.raises(ClientError) as raised:
        ses_alerts.send_alert(
            RECIPIENT,
            "Subject",
            "<p>HTML</p>",
            "Text",
            UNSUBSCRIBE_URL,
        )

    assert raised.value is error


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("to", "investor@monash.edu\r\nBcc: attacker@evil.com"),
        ("subject", "Good news\r\nBcc: attacker@evil.com"),
        (
            "unsubscribe_url",
            "https://api.stocksinhand.com.au/unsubscribe?t=token\r\n"
            "Bcc: attacker@evil.com",
        ),
    ],
)
def test_send_alert_rejects_header_injection(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    """User-controlled header values must not permit CRLF injection."""
    client = MagicMock()
    arguments = {
        "to": RECIPIENT,
        "subject": "BHP news",
        "html": "<p>HTML</p>",
        "text": "Text",
        "unsubscribe_url": UNSUBSCRIBE_URL,
    }
    arguments[field] = value
    monkeypatch.setattr(ses_alerts, "_client", client)
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", SENDER, raising=False)

    with pytest.raises(ValueError):
        ses_alerts.send_alert(**arguments)

    client.assert_not_called()


def test_render_alert_email_escapes_html_and_handles_missing_summary() -> None:
    """Templates must escape source content and omit absent summaries."""
    subject, html, text = render_alert_email(
        ticker_symbol="BHP<script>",
        company_name="BHP & Co <holdings>",
        artifact_title="Update <img src=x onerror=alert(1)>",
        summary_text=None,
        sentiment_label="negative",
        confidence_score=0.8123,
        news_url="https://app.example.test/ticker/BHP/news/",
        unsubscribe_url="https://app.example.test/unsubscribe?t=signed-token",
    )

    assert "BHP<script>" in subject
    assert "BHP&lt;script&gt;" in html
    assert "BHP &amp; Co &lt;holdings&gt;" in html
    assert "Update &lt;img src=x onerror=alert(1)&gt;" in html
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "No summary available" not in html
    assert "No summary available" not in text
    assert "81.2%" in html
    assert "81.2%" in text
    assert "https://app.example.test/ticker/BHP/news/" in text
    assert "https://app.example.test/unsubscribe?t=signed-token" in text


def test_render_alert_email_includes_an_escaped_summary() -> None:
    """Available summaries should appear safely in HTML and plain text."""
    _subject, html, text = render_alert_email(
        ticker_symbol="CSL",
        company_name="CSL Limited",
        artifact_title="Results update",
        summary_text="Revenue rose <strong>10%</strong>.\nGuidance was retained.",
        sentiment_label="positive",
        confidence_score=0.75,
        news_url="https://app.example.test/ticker/CSL/news/",
        unsubscribe_url="https://app.example.test/unsubscribe?t=signed-token",
    )

    assert "<h2>Summary</h2>" in html
    assert "Revenue rose &lt;strong&gt;10%&lt;/strong&gt;." in html
    assert "<br>" in html
    assert "Revenue rose <strong>10%</strong>." in text
    assert "Confidence:" in html
    assert ">75%</strong>" in html


@pytest.mark.parametrize(
    "confidence",
    [-0.01, 1.01, float("nan"), float("inf"), "not-a-number"],
)
def test_render_alert_email_rejects_invalid_confidence(
    confidence: object,
) -> None:
    """Confidence must be a finite number from zero through one."""
    with pytest.raises(ValueError, match="confidence_score"):
        render_alert_email(
            ticker_symbol="BHP",
            company_name="BHP Group",
            artifact_title="Results update",
            summary_text=None,
            sentiment_label="negative",
            confidence_score=confidence,  # type: ignore[arg-type]
            news_url="https://stocksinhand.com.au/ticker/BHP/news/",
            unsubscribe_url="https://stocksinhand.com.au/unsubscribe?t=token",
        )
