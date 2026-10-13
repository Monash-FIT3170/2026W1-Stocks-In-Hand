"""Brevo transactional-email boundary for watchlist alerts."""

from __future__ import annotations

import hashlib
import logging
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import httpx
from email_validator import EmailNotValidError, validate_email

from app.core.config import settings
from app.services.email_sender import (
    Accepted,
    Misconfigured,
    OutgoingEmail,
    RecipientRejected,
    SendOutcome,
    SendPacer,
    Unavailable,
    check_message,
    mailbox,
)


LOGGER = logging.getLogger(__name__)
DRY_RUN_SENDER = "notifications@example.invalid"
_SAFE_ERROR_CODE = re.compile(r"[^a-zA-Z0-9_.-]+")


class BrevoAlertConfigurationError(ValueError):
    """Raised when live Brevo delivery lacks required configuration."""


class BrevoApiError(RuntimeError):
    """A sanitized non-success response from the Brevo API."""

    def __init__(self, *, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code[:128] or "brevo_api_error"
        self.retryable = status_code in {408, 429} or status_code >= 500
        super().__init__(f"Brevo API request failed with status {status_code}")


def _safe_header(value: str, *, field: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    if "\r" in cleaned or "\n" in cleaned:
        raise ValueError(f"{field} must not contain line breaks")
    return cleaned


def _safe_url(value: str, *, field: str) -> str:
    cleaned = _safe_header(value, field=field)
    if "<" in cleaned or ">" in cleaned:
        raise ValueError(f"{field} must not contain angle brackets")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute HTTP or HTTPS URL")
    return cleaned


def _mailbox(value: str, *, field: str) -> str:
    cleaned = _safe_header(value, field=field)
    try:
        validated = validate_email(
            cleaned,
            allow_display_name=False,
            allow_smtputf8=False,
            check_deliverability=False,
        )
    except EmailNotValidError as exc:
        raise ValueError(f"{field} must contain one valid email address") from exc
    return str(validated.ascii_email or validated.normalized)


def _api_base_url() -> str:
    base_url = _safe_url(settings.BREVO_API_BASE_URL, field="BREVO_API_BASE_URL")
    if not settings.NOTIFICATIONS_DRY_RUN and urlsplit(base_url).scheme != "https":
        raise BrevoAlertConfigurationError(
            "BREVO_API_BASE_URL must use HTTPS for live delivery"
        )
    return base_url.rstrip("/")


@lru_cache(maxsize=1)
def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(10.0))


def _response_error_code(response: httpx.Response) -> str:
    raw_code = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        raw_code = str(payload.get("code") or "")
    normalized = _SAFE_ERROR_CODE.sub("_", raw_code.strip()).strip("_")
    return normalized or f"brevo_http_{response.status_code}"


def _dry_run_message_id(  # pylint: disable=too-many-arguments
    *,
    sender: str,
    recipient: str,
    subject: str,
    html: str,
    text: str,
    unsubscribe_url: str | None,
) -> str:
    digest_source = "\0".join(
        (sender, recipient, subject, html, text, unsubscribe_url or "")
    ).encode("utf-8")
    return f"dry-run-{hashlib.sha256(digest_source).hexdigest()[:16]}"


def send_email(  # pylint: disable=too-many-arguments,too-many-locals
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    unsubscribe_url: str | None = None,
) -> str:
    """Send one Brevo transactional email and return its message identifier."""
    recipient = _mailbox(to, field="recipient")
    safe_subject = _safe_header(subject, field="subject")
    safe_unsubscribe_url = (
        _safe_url(unsubscribe_url, field="unsubscribe_url")
        if unsubscribe_url is not None
        else None
    )

    if settings.NOTIFICATIONS_DRY_RUN:
        sender = DRY_RUN_SENDER
    else:
        if safe_unsubscribe_url and urlsplit(safe_unsubscribe_url).scheme != "https":
            raise ValueError("unsubscribe_url must use HTTPS for live delivery")
        if not settings.ALERT_SENDER_EMAIL.strip():
            raise BrevoAlertConfigurationError(
                "ALERT_SENDER_EMAIL is required for live Brevo delivery"
            )
        if not settings.BREVO_API_KEY.strip():
            raise BrevoAlertConfigurationError(
                "BREVO_API_KEY is required for live Brevo delivery"
            )
        sender = _mailbox(settings.ALERT_SENDER_EMAIL, field="sender")

    if settings.NOTIFICATIONS_DRY_RUN:
        message_id = _dry_run_message_id(
            sender=sender,
            recipient=recipient,
            subject=safe_subject,
            html=str(html),
            text=str(text),
            unsubscribe_url=safe_unsubscribe_url,
        )
        LOGGER.info(
            "Brevo send dry run subject_length=%d message_id=%s",
            len(safe_subject),
            message_id,
        )
        return message_id

    headers: dict[str, str] = {}
    if safe_unsubscribe_url:
        # No List-Unsubscribe-Post: the link is a static CloudFront page that
        # only accepts GET, so an RFC 8058 one-click POST would fail.
        headers["List-Unsubscribe"] = f"<{safe_unsubscribe_url}>"

    payload: dict[str, Any] = {
        "sender": {
            "email": sender,
            "name": _safe_header(settings.ALERT_SENDER_NAME, field="sender name"),
        },
        "to": [{"email": recipient}],
        "subject": safe_subject,
        "htmlContent": str(html),
        "textContent": str(text),
    }
    if headers:
        payload["headers"] = headers

    response = _client().post(
        f"{_api_base_url()}/smtp/email",
        headers={
            "accept": "application/json",
            "api-key": settings.BREVO_API_KEY,
            "content-type": "application/json",
        },
        json=payload,
    )
    if not 200 <= response.status_code < 300:
        raise BrevoApiError(
            status_code=response.status_code,
            code=_response_error_code(response),
        )

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("Brevo response was not valid JSON") from exc
    message_id = str(result.get("messageId") or "").strip() if isinstance(
        result, dict
    ) else ""
    if not message_id:
        raise RuntimeError("Brevo response did not include messageId")

    LOGGER.info("Brevo alert sent message_id=%s", message_id)
    return message_id


def _send_endpoint(base_url: str) -> str | None:
    """Brevo's send endpoint under ``base_url``, or None unless that is HTTPS."""
    base = base_url.strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme != "https" or not parts.netloc:
        return None
    return f"{base}/smtp/email"


def _outcome(response: httpx.Response) -> SendOutcome:
    """What Brevo's answer means, keeping none of its message text."""
    if not 200 <= response.status_code < 300:
        code = _response_error_code(response)[:128]
        if response.status_code in {400, 404, 422}:
            return RecipientRejected(code, "Brevo rejected the recipient or message")
        if response.status_code in {408, 429} or response.status_code >= 500:
            return Unavailable(code)
        return Misconfigured(code)
    try:
        body = response.json()
    except ValueError:
        body = None
    message_id = (
        str(body.get("messageId") or "").strip() if isinstance(body, dict) else ""
    )
    if not message_id:
        # Brevo may have sent it anyway, so a retry can send it twice. Taking
        # it as sent instead could lose the email without anyone knowing.
        return Unavailable("brevo_send_failed")
    LOGGER.info("Brevo email sent message_id=%s", message_id)
    return Accepted(message_id)


@dataclass(frozen=True, kw_only=True)
class BrevoEmailSender:
    """Sends through Brevo's transactional email API.

    Brevo answers 400, 404 or 422 when it will never take the recipient or the
    message, and 408, 429 or 5xx when a retry may succeed. Any other refusal,
    such as a bad key or no credit, means our account or settings need fixing.
    A ``pacer`` paces only the request to Brevo.
    """

    api_key: str = field(repr=False)
    sender_email: str
    sender_name: str
    base_url: str
    client: httpx.Client | None = None
    pacer: SendPacer | None = None

    @classmethod
    def from_settings(cls, *, pacer: SendPacer | None = None) -> BrevoEmailSender:
        """The sender the ``BREVO_*`` and ``ALERT_SENDER_*`` settings describe."""
        return cls(
            api_key=settings.BREVO_API_KEY,
            sender_email=settings.ALERT_SENDER_EMAIL,
            sender_name=settings.ALERT_SENDER_NAME,
            base_url=settings.BREVO_API_BASE_URL,
            pacer=pacer,
        )

    def send(self, email: OutgoingEmail) -> SendOutcome:
        checked = check_message(email, require_https=True)
        if not isinstance(checked, OutgoingEmail):
            return checked
        endpoint = _send_endpoint(self.base_url)
        if not self.api_key.strip() or not self.sender_email.strip() or endpoint is None:
            return Misconfigured("brevo_configuration_error")
        sender = mailbox(self.sender_email)
        sender_name = self.sender_name.strip()
        if sender is None or not sender_name or "\r" in sender_name or "\n" in sender_name:
            return Misconfigured("invalid_notification_configuration")

        payload: dict[str, Any] = {
            "sender": {"email": sender, "name": sender_name},
            "to": [{"email": checked.to}],
            "subject": checked.subject,
            "htmlContent": checked.html,
            "textContent": checked.text,
        }
        if checked.unsubscribe_url:
            payload["headers"] = {"List-Unsubscribe": f"<{checked.unsubscribe_url}>"}

        pace = self.pacer.pace() if self.pacer is not None else nullcontext()
        try:
            with pace:
                response = (self.client or _client()).post(
                    endpoint,
                    headers={
                        "accept": "application/json",
                        "api-key": self.api_key,
                        "content-type": "application/json",
                    },
                    json=payload,
                )
            return _outcome(response)
        except httpx.HTTPError:
            return Unavailable("brevo_transport_error")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.warning("Brevo send failed error_type=%s", type(exc).__name__)
            return Unavailable("brevo_send_failed")
