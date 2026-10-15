"""The email sender interface and the senders that need no provider.

Every sender makes the same checks before it sends. The dry-run sender only
logs, and the recording sender keeps each email for tests to read.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.config import settings
from app.services import email_sender
from app.services.brevo_alerts import BrevoEmailSender
from app.services.email_sender import (
    Accepted,
    DryRunEmailSender,
    Misconfigured,
    OutgoingEmail,
    RecipientRejected,
    RecordingEmailSender,
    SendPacer,
    Unavailable,
    check_message,
    configured_sender,
)

ALERT = OutgoingEmail(
    to="investor@example.com",
    subject="BHP watchlist alert",
    html="<p>html</p>",
    text="plain text",
    unsubscribe_url="https://app.example.test/unsubscribe/?t=signed",
)
LOCAL_ALERT = replace(ALERT, unsubscribe_url="http://localhost:3000/unsubscribe/?t=signed")
INVALID_RECIPIENT = RecipientRejected("invalid_recipient", "Recipient address is invalid")
INVALID_MESSAGE = Misconfigured("invalid_notification_configuration")


def test_recording_sender_keeps_each_email_and_accepts_it() -> None:
    sender = RecordingEmailSender()

    assert sender.send(ALERT) == Accepted("recorded-1")
    assert sender.send(LOCAL_ALERT) == Accepted("recorded-2")
    assert sender.sent == [ALERT, LOCAL_ALERT]


def test_recording_sender_answers_scripted_outcomes_in_order_then_accepts() -> None:
    sender = RecordingEmailSender(
        [Unavailable("rate_limit"), RecipientRejected("invalid_parameter")]
    )

    assert [sender.send(ALERT) for _ in range(3)] == [
        Unavailable("rate_limit"),
        RecipientRejected("invalid_parameter"),
        Accepted("recorded-3"),
    ]
    assert len(sender.sent) == 3


def test_recording_sender_can_answer_from_the_email() -> None:
    sender = RecordingEmailSender(lambda email: Misconfigured(email.subject))

    assert sender.send(ALERT) == Misconfigured("BHP watchlist alert")
    assert sender.sent == [ALERT]


def test_recording_sender_keeps_no_email_that_fails_the_checks() -> None:
    sender = RecordingEmailSender()

    assert sender.send(replace(ALERT, to="not-an-email")) == INVALID_RECIPIENT
    assert sender.sent == []


def test_a_checked_email_comes_back_ready_to_send() -> None:
    email = replace(ALERT, to=" investor@BÜCHER.de ", subject=" BHP watchlist alert ")

    assert check_message(email, require_https=True) == replace(
        ALERT,
        to="investor@xn--bcher-kva.de",
    )


@pytest.mark.parametrize(
    ("email", "outcome"),
    [
        (replace(ALERT, to="not-an-email"), INVALID_RECIPIENT),
        (replace(ALERT, to="Investor <investor@example.com>"), INVALID_RECIPIENT),
        (replace(ALERT, to="investor@example.com\r\nBcc: x@example.com"), INVALID_RECIPIENT),
        (replace(ALERT, subject="Alert\r\nBcc: attacker@example.com"), INVALID_MESSAGE),
        (replace(ALERT, subject="  "), INVALID_MESSAGE),
        (replace(ALERT, unsubscribe_url="/unsubscribe/?t=signed"), INVALID_MESSAGE),
        (replace(ALERT, unsubscribe_url="https://app.example.test/<x>"), INVALID_MESSAGE),
        (replace(ALERT, unsubscribe_url="mailto:unsubscribe@example.com"), INVALID_MESSAGE),
        # urlsplit raises for these hosts, and the checks must answer instead.
        (replace(ALERT, unsubscribe_url="https://[app.example.test/"), INVALID_MESSAGE),
        (replace(ALERT, unsubscribe_url="https://[not-an-ip]/"), INVALID_MESSAGE),
    ],
)
def test_check_message_stops_an_email_no_sender_may_send(
    email: OutgoingEmail,
    outcome: RecipientRejected | Misconfigured,
) -> None:
    assert check_message(email, require_https=False) == outcome


def test_an_http_unsubscribe_link_is_stopped_only_when_https_is_required() -> None:
    assert check_message(LOCAL_ALERT, require_https=False) == LOCAL_ALERT
    assert check_message(LOCAL_ALERT, require_https=True) == INVALID_MESSAGE


def test_dry_run_gives_the_same_email_the_same_id() -> None:
    sender = DryRunEmailSender()

    first = sender.send(LOCAL_ALERT)

    assert isinstance(first, Accepted)
    assert first.message_id.startswith("dry-run-")
    assert sender.send(LOCAL_ALERT) == first
    assert sender.send(replace(LOCAL_ALERT, subject="Another alert")) != first


def test_dry_run_makes_the_same_checks_as_a_real_send() -> None:
    assert DryRunEmailSender().send(replace(ALERT, to="not-an-email")) == INVALID_RECIPIENT


def test_pacer_spaces_the_sends_it_wraps() -> None:
    times = iter([10.0, 10.25, 11.25, 13.0, 13.0])
    sleeps: list[float] = []
    pacer = SendPacer(1.0, clock=lambda: next(times), sleep=sleeps.append)

    for _ in range(3):
        with pacer.pace():
            pass

    assert sleeps == [0.75]


def test_configured_sender_follows_the_dry_run_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", True, raising=False)

    assert isinstance(configured_sender(), DryRunEmailSender)
    assert isinstance(configured_sender(paced=True), DryRunEmailSender)

    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(settings, "ALERT_SENDER_EMAIL", "alerts@example.com", raising=False)
    live = configured_sender()

    assert isinstance(live, BrevoEmailSender)
    assert live.sender_email == "alerts@example.com"
    assert live.pacer is None
    assert configured_sender(paced=True).pacer is email_sender.ALERT_PACER
