"""Brevo transactional-email boundary for watchlist alerts."""

from __future__ import annotations

import hashlib
import logging
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import httpx
from email_validator import EmailNotValidError, validate_email

from app.core.config import settings


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
        headers["List-Unsubscribe"] = f"<{safe_unsubscribe_url}>"
        if settings.ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED:
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

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
