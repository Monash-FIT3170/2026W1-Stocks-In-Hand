"""The email sender: the one way the product sends email.

A caller hands a sender an ``OutgoingEmail`` and gets back one of four
outcomes: ``Accepted``, ``RecipientRejected``, ``Unavailable`` (temporary, so
a retry may succeed) or ``Misconfigured`` (our settings or the message are
wrong, so a retry helps only after a fix). A sender never raises for a
provider, network or configuration problem. Each caller decides what an
outcome means for it.

``configured_sender()`` returns the sender the deployment configures: the
Brevo adapter in ``brevo_alerts``, or ``DryRunEmailSender`` when
``NOTIFICATIONS_DRY_RUN`` is set. Tests use ``RecordingEmailSender``.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Protocol
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email

from app.core.config import settings


LOGGER = logging.getLogger(__name__)
DRY_RUN_SENDER = "notifications@example.invalid"
_INVALID_MESSAGE = "invalid_notification_configuration"


@dataclass(frozen=True)
class OutgoingEmail:
    """One email to one recipient, with an HTML body and a plain-text body.

    An ``unsubscribe_url`` becomes the List-Unsubscribe header. No sender adds
    List-Unsubscribe-Post: the link is a static CloudFront page that only
    accepts GET, so an RFC 8058 one-click POST to it would fail.
    """

    to: str
    subject: str
    html: str
    text: str
    unsubscribe_url: str | None = None


@dataclass(frozen=True)
class Accepted:
    """The provider took the email for delivery."""

    message_id: str


@dataclass(frozen=True)
class RecipientRejected:
    """The address, or this email, will never be accepted."""

    code: str
    detail: str = "The provider rejected the recipient or message"


@dataclass(frozen=True)
class Unavailable:
    """The email could not be sent now. A retry may succeed."""

    code: str


@dataclass(frozen=True)
class Misconfigured:
    """Our settings or the email are wrong. A retry helps only after a fix."""

    code: str


SendOutcome = Accepted | RecipientRejected | Unavailable | Misconfigured


class EmailSender(Protocol):
    """Sends one email and reports the outcome, never raising for a send problem."""

    def send(self, email: OutgoingEmail) -> SendOutcome: ...


def check_message(
    email: OutgoingEmail,
    *,
    require_https: bool,
) -> OutgoingEmail | RecipientRejected | Misconfigured:
    """Make the checks every sender makes before it sends.

    Returns the email as it should be sent, with the recipient in ASCII form
    and the subject and unsubscribe link trimmed, or the outcome that stops
    it. A real send needs an HTTPS unsubscribe link. Dry runs and tests may
    use a local HTTP one.
    """
    recipient = mailbox(email.to)
    if recipient is None:
        return RecipientRejected("invalid_recipient", "Recipient address is invalid")
    subject = _single_line(email.subject)
    if subject is None:
        return Misconfigured(_INVALID_MESSAGE)
    unsubscribe_url = None
    if email.unsubscribe_url is not None:
        unsubscribe_url = _web_link(email.unsubscribe_url, require_https=require_https)
        if unsubscribe_url is None:
            return Misconfigured(_INVALID_MESSAGE)
    return replace(email, to=recipient, subject=subject, unsubscribe_url=unsubscribe_url)


def mailbox(address: str) -> str | None:
    """The one mailbox ``address`` names, in the ASCII form email is sent to.

    Returns None unless ``address`` is exactly one valid address, with no
    display name and nothing that needs SMTPUTF8.
    """
    text = _single_line(address)
    if text is None:
        return None
    try:
        validated = validate_email(
            text,
            allow_display_name=False,
            allow_smtputf8=False,
            check_deliverability=False,
        )
    except EmailNotValidError:
        return None
    return str(validated.ascii_email or validated.normalized)


def _single_line(value: str) -> str | None:
    """``value`` trimmed, or None when that leaves nothing or more than one line."""
    text = value.strip()
    if not text or "\r" in text or "\n" in text:
        return None
    return text


def _web_link(value: str, *, require_https: bool) -> str | None:
    """``value`` trimmed, or None unless it is an absolute link safe in a header."""
    text = _single_line(value)
    if text is None or "<" in text or ">" in text:
        return None
    parts = urlsplit(text)
    schemes = {"https"} if require_https else {"http", "https"}
    if parts.scheme not in schemes or not parts.netloc:
        return None
    return text


class SendPacer:
    """Spaces the sends it wraps at least ``interval`` seconds apart."""

    def __init__(
        self,
        interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_send: float | None = None

    @contextmanager
    def pace(self) -> Iterator[None]:
        """Wait out the interval since the last send, then hold the pacer for this one."""
        with self._lock:
            if self._last_send is not None:
                delay = self._interval - (self._clock() - self._last_send)
                if delay > 0:
                    self._sleep(delay)
            try:
                yield
            finally:
                self._last_send = self._clock()


# Live alert fan-out sends at most one email a second. The pacer lives as long
# as the Lambda container, so the spacing also holds across warm invocations,
# but separate containers do not share it.
ALERT_PACER = SendPacer(1.0)


class DryRunEmailSender:
    """Accepts every email that passes the checks and logs it instead of sending.

    The message id is a digest of the email, so a replay gets the same id.
    """

    def send(self, email: OutgoingEmail) -> SendOutcome:
        checked = check_message(email, require_https=False)
        if not isinstance(checked, OutgoingEmail):
            return checked
        digest_source = "\0".join(
            (
                DRY_RUN_SENDER,
                checked.to,
                checked.subject,
                checked.html,
                checked.text,
                checked.unsubscribe_url or "",
            )
        ).encode("utf-8")
        message_id = f"dry-run-{hashlib.sha256(digest_source).hexdigest()[:16]}"
        LOGGER.info(
            "Email send dry run subject_length=%d message_id=%s",
            len(checked.subject),
            message_id,
        )
        return Accepted(message_id)


class RecordingEmailSender:
    """Keeps every email that passes the checks, for tests to read in ``sent``.

    It answers with ``outcomes`` in order and accepts once they run out.
    ``outcomes`` can instead be a function of the email, which also lets a
    test look at the database at the moment the email goes out.
    """

    def __init__(
        self,
        outcomes: Iterable[SendOutcome] | Callable[[OutgoingEmail], SendOutcome] = (),
        *,
        require_https: bool = False,
    ) -> None:
        self.sent: list[OutgoingEmail] = []
        self._require_https = require_https
        self._answer = outcomes if callable(outcomes) else None
        self._scripted = iter(() if callable(outcomes) else outcomes)

    def send(self, email: OutgoingEmail) -> SendOutcome:
        checked = check_message(email, require_https=self._require_https)
        if not isinstance(checked, OutgoingEmail):
            return checked
        self.sent.append(checked)
        if self._answer is not None:
            return self._answer(checked)
        return next(self._scripted, None) or Accepted(f"recorded-{len(self.sent)}")


def configured_sender(*, paced: bool = False) -> EmailSender:
    """The sender the deployment configures, reading its settings on each call.

    ``paced`` shares ``ALERT_PACER`` with every other paced sender in the
    process. A dry run is never paced, because it sends nothing.
    """
    if settings.NOTIFICATIONS_DRY_RUN:
        return DryRunEmailSender()
    # The Brevo adapter is built on this module's outcomes, so it is imported
    # here rather than at the top, where the two modules would import each other.
    from app.services.brevo_alerts import (  # pylint: disable=import-outside-toplevel
        BrevoEmailSender,
    )

    return BrevoEmailSender.from_settings(pacer=ALERT_PACER if paced else None)


def current_sender() -> EmailSender:
    """``configured_sender()`` as a FastAPI dependency.

    It looks ``configured_sender`` up on every request, so a test that
    replaces it reaches the routes as well as the notify worker.
    """
    return configured_sender()
