"""Amazon SESv2 boundary for watchlist alert verification and delivery."""

from __future__ import annotations

import hashlib
import logging
from email.message import EmailMessage
from email.policy import SMTP
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from email_validator import EmailNotValidError, validate_email

from app.core.config import settings


LOGGER = logging.getLogger(__name__)
DRY_RUN_SENDER = "notifications@example.invalid"


class SesAlertConfigurationError(ValueError):
    """Raised when live SES delivery lacks required configuration."""


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


def _client_error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code") or "")


@lru_cache(maxsize=1)
def _client() -> Any:
    return boto3.client(
        "sesv2",
        region_name=settings.AWS_REGION,
        endpoint_url=settings.AWS_ENDPOINT_URL_SES or None,
    )


def request_verification(email: str) -> None:
    """Start SES identity verification for one recipient address."""
    recipient = _mailbox(email, field="email")
    if settings.NOTIFICATIONS_DRY_RUN:
        LOGGER.info("SES verification dry run")
        return

    try:
        _client().create_email_identity(EmailIdentity=recipient)
    except ClientError as exc:
        if _client_error_code(exc) != "AlreadyExistsException":
            raise

    LOGGER.info("SES verification requested")


def identity_status(email: str) -> str:
    """Return the local verification state for an SES email identity."""
    recipient = _mailbox(email, field="email")
    if settings.NOTIFICATIONS_DRY_RUN:
        LOGGER.info("SES identity check dry run")
        return "pending"

    try:
        response = _client().get_email_identity(EmailIdentity=recipient)
    except ClientError as exc:
        if _client_error_code(exc) == "NotFoundException":
            return "unverified"
        raise

    if response.get("VerifiedForSendingStatus") is True:
        status = "verified"
    else:
        verification_status = str(
            response.get("VerificationStatus") or ""
        ).upper()
        if verification_status == "FAILED":
            status = "failed"
        elif verification_status == "NOT_STARTED":
            status = "unverified"
        else:
            status = "pending"

    LOGGER.info(
        "SES identity checked status=%s",
        status,
    )
    return status


def _message(  # pylint: disable=too-many-arguments
    *,
    sender: str,
    recipient: str,
    subject: str,
    html: str,
    text: str,
    unsubscribe_url: str,
    one_click: bool,
) -> EmailMessage:
    message = EmailMessage(policy=SMTP)
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    if one_click:
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def send_alert(  # pylint: disable=too-many-locals
    to: str,
    subject: str,
    html: str,
    text: str,
    unsubscribe_url: str,
) -> str:
    """Send one multipart alert and return the SES message identifier."""
    recipient = _mailbox(to, field="recipient")
    safe_subject = _safe_header(subject, field="subject")
    safe_unsubscribe_url = _safe_url(
        unsubscribe_url,
        field="unsubscribe_url",
    )
    one_click = settings.ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED

    if settings.NOTIFICATIONS_DRY_RUN:
        sender = DRY_RUN_SENDER
    else:
        if urlsplit(safe_unsubscribe_url).scheme != "https":
            raise ValueError("unsubscribe_url must use HTTPS for live delivery")
        if not settings.ALERT_SENDER_EMAIL.strip():
            raise SesAlertConfigurationError(
                "ALERT_SENDER_EMAIL is required for live SES delivery"
            )
        sender = _mailbox(
            settings.ALERT_SENDER_EMAIL,
            field="sender",
        )

    message = _message(
        sender=sender,
        recipient=recipient,
        subject=safe_subject,
        html=str(html),
        text=str(text),
        unsubscribe_url=safe_unsubscribe_url,
        one_click=one_click,
    )
    raw_message = message.as_bytes()

    if settings.NOTIFICATIONS_DRY_RUN:
        digest_source = "\0".join(
            (
                sender,
                recipient,
                safe_subject,
                str(html),
                str(text),
                safe_unsubscribe_url,
            )
        ).encode("utf-8")
        digest = hashlib.sha256(digest_source).hexdigest()[:16]
        message_id = f"dry-run-{digest}"
        LOGGER.info(
            "SES send dry run subject_length=%d bytes=%d "
            "message_id=%s",
            len(safe_subject),
            len(raw_message),
            message_id,
        )
        return message_id

    response = _client().send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [recipient]},
        Content={"Raw": {"Data": raw_message}},
    )
    message_id = str(response.get("MessageId") or "").strip()
    if not message_id:
        raise RuntimeError("SES SendEmail response did not include MessageId")

    LOGGER.info(
        "SES alert sent message_id=%s",
        message_id,
    )
    return message_id
