"""Brevo behind the email sender interface.

``BrevoEmailSender`` posts each email to Brevo's transactional email API and
turns Brevo's answer into a send outcome, keeping none of Brevo's message text.
"""

from __future__ import annotations

import logging
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import httpx

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
_SAFE_ERROR_CODE = re.compile(r"[^a-zA-Z0-9_.-]+")


@lru_cache(maxsize=1)
def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(10.0))


def _response_error_code(response: httpx.Response) -> str:
    """Brevo's error code in a form safe to store, or one named by the status."""
    raw_code = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        raw_code = str(payload.get("code") or "")
    normalized = _SAFE_ERROR_CODE.sub("_", raw_code.strip()).strip("_")
    return (normalized or f"brevo_http_{response.status_code}")[:128]


def _send_endpoint(base_url: str) -> str | None:
    """Brevo's send endpoint under ``base_url``, or None unless that is HTTPS."""
    base = base_url.strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme != "https" or not parts.netloc:
        return None
    return f"{base}/smtp/email"


def _outcome(response: httpx.Response) -> SendOutcome:
    """What Brevo's answer means."""
    if not 200 <= response.status_code < 300:
        code = _response_error_code(response)
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
