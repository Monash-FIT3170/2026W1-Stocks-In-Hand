"""Contracts for the SES watchlist notification worker."""

# pylint: disable=duplicate-code,protected-access,too-many-arguments,too-many-positional-arguments

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.core.config import settings
from lambdas import notify


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _enable_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the enabled worker unless a test explicitly selects dark mode."""
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True, raising=False)
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")


def _message_body(**overrides: object) -> dict[str, object]:
    """Return one valid, versioned notification message body."""
    body: dict[str, object] = {
        "schema_version": 1,
        "artifact_id": str(uuid4()),
        "ticker": "BHP",
        "scrape_run_id": str(uuid4()),
        "sentiment_label": "negative",
        "confidence_score": 0.82,
    }
    body.update(overrides)
    return body


def _sqs_record(message_id: str = "notification-1", **overrides: object) -> dict:
    """Wrap a notification body in the SQS event-record shape."""
    return {
        "messageId": message_id,
        "body": json.dumps(_message_body(**overrides)),
        "attributes": {"ApproximateReceiveCount": "1"},
    }


def _context() -> notify.NotificationContext:
    """Build canonical artifact values without touching the database."""
    message = notify.NotificationMessage.model_validate(_message_body())
    return notify.NotificationContext(
        message=message,
        ticker_id=uuid4(),
        ticker_symbol=message.ticker,
        company_name="BHP Group Limited",
        artifact_title="Half year results",
        summary_text=None,
        sentiment_label=message.sentiment_label,
        confidence_score=message.confidence_score,
    )


def _preferences(**overrides: object) -> notify.WatcherPreferences:
    """Build one enabled, locally verified watcher and matching rule."""
    investor_id = overrides.pop("investor_id", uuid4())
    rule = overrides.pop(
        "rule",
        notify.RulePreferences(
            id=uuid4(),
            enabled=True,
            rule_type="sentiment_threshold",
            sentiment_labels=("negative",),
            min_confidence=Decimal("0.75"),
        ),
    )
    values: dict[str, object] = {
        "investor_id": investor_id,
        "subscription_id": uuid4(),
        "email": "investor@example.com",
        "enabled": True,
        "verification_status": "verified",
        "verification_requested_at": datetime.now(timezone.utc),
        "unsubscribe_token_hash": "a" * 64,
        "rule": rule,
    }
    values.update(overrides)
    return notify.WatcherPreferences(**values)  # type: ignore[arg-type]


def _lease(investor_id: UUID, *, rollup: bool = False) -> notify.DeliveryLease:
    """Build a detached claim lease."""
    return notify.DeliveryLease(
        id=uuid4(),
        investor_id=investor_id,
        claimed_at=datetime.now(timezone.utc),
        rollup=rollup,
    )


def _client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "private SES detail"}},
        "SendEmail",
    )


def test_notification_message_parser_accepts_the_versioned_contract() -> None:
    """A valid producer payload should reach the worker as typed values."""
    artifact_id = uuid4()
    scrape_run_id = uuid4()

    message = notify.parse_notification_record(
        _sqs_record(
            artifact_id=str(artifact_id),
            scrape_run_id=str(scrape_run_id),
            ticker=" bhp ",
            confidence_score="0.7500",
        )
    )

    assert message.schema_version == 1
    assert message.artifact_id == artifact_id
    assert message.scrape_run_id == scrape_run_id
    assert message.ticker == "BHP"
    assert message.sentiment_label == "negative"
    assert Decimal(str(message.confidence_score)) == Decimal("0.7500")


@pytest.mark.parametrize(
    "body",
    [
        "not-json",
        json.dumps({}),
        json.dumps(_message_body(schema_version=2)),
        json.dumps(_message_body(confidence_score=-0.01)),
        json.dumps(_message_body(confidence_score=1.01)),
        json.dumps(_message_body(sentiment_label="unknown")),
        json.dumps(_message_body(extra_field="must be rejected")),
    ],
)
def test_notification_message_parser_rejects_poison_payloads(body: str) -> None:
    """Malformed queue messages are permanent failures, not retry candidates."""
    record = _sqs_record()
    record["body"] = body

    with pytest.raises(ValueError) as raised:
        notify.parse_notification_record(record)

    assert getattr(raised.value, "code", None) == "invalid_notification_message"


@pytest.mark.parametrize(
    ("enabled", "labels", "threshold", "label", "confidence", "expected"),
    [
        (True, ["negative"], "0.75", "negative", "0.75", True),
        (True, ["negative"], "0.75", "negative", "0.7499", False),
        (True, ["negative"], "0.75", "positive", "0.99", False),
        (False, ["negative"], "0.75", "negative", "0.99", False),
    ],
)
def test_rule_matching_covers_threshold_boundaries(
    enabled: bool,
    labels: list[str],
    threshold: str,
    label: str,
    confidence: str,
    expected: bool,
) -> None:
    """A rule fires only when enabled, labelled, and at its threshold."""
    rule = SimpleNamespace(
        enabled=enabled,
        sentiment_labels=labels,
        min_confidence=Decimal(threshold),
    )

    assert notify._rule_matches(rule, label, Decimal(confidence)) is expected


@pytest.mark.parametrize(
    "preferences",
    [
        None,
        _preferences(enabled=False),
        _preferences(
            rule=notify.RulePreferences(
                id=uuid4(),
                enabled=True,
                rule_type="sentiment_threshold",
                sentiment_labels=("positive",),
                min_confidence=Decimal("0.75"),
            )
        ),
        _preferences(
            rule=notify.RulePreferences(
                id=uuid4(),
                enabled=True,
                rule_type="sentiment_threshold",
                sentiment_labels=("negative",),
                min_confidence=Decimal("0.99"),
            )
        ),
    ],
)
def test_subscription_and_rule_filters_skip_before_claim(
    monkeypatch: pytest.MonkeyPatch,
    preferences: notify.WatcherPreferences | None,
) -> None:
    """Disabled or non-matching watchers must never create ledger rows."""
    claim_direct = Mock()
    monkeypatch.setattr(notify, "_load_preferences", lambda _id: preferences)
    monkeypatch.setattr(notify, "_claim_direct", claim_direct)

    notify._process_watcher(_context(), uuid4())

    claim_direct.assert_not_called()


def test_record_fans_out_to_each_distinct_watcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One artifact message should process every watcher returned by CRUD."""
    context = _context()
    investor_ids = [uuid4(), uuid4()]
    process_watcher = Mock()
    db = object()

    @contextmanager
    def fake_session() -> Iterator[object]:
        yield db

    monkeypatch.setattr(
        notify,
        "parse_notification_record",
        lambda _record: context.message,
    )
    monkeypatch.setattr(notify, "_load_context", lambda _message: context)
    monkeypatch.setattr(notify, "database_session", fake_session)
    monkeypatch.setattr(
        notify.watchlist_ticker_crud,
        "investor_ids_watching",
        lambda actual_db, ticker_id: investor_ids
        if actual_db is db and ticker_id == context.ticker_id
        else [],
    )
    monkeypatch.setattr(notify, "_process_watcher", process_watcher)

    notify._process_record(_sqs_record())

    assert process_watcher.call_args_list == [
        ((context, investor_ids[0]),),
        ((context, investor_ids[1]),),
    ]


def test_record_finishes_siblings_before_returning_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One temporary investor failure must not block later investors."""
    context = _context()
    investor_ids = [uuid4(), uuid4()]
    processed: list[UUID] = []

    @contextmanager
    def fake_session() -> Iterator[object]:
        yield object()

    def process_watcher(_context_value: object, investor_id: UUID) -> None:
        processed.append(investor_id)
        if investor_id == investor_ids[0]:
            raise notify.RetryableNotificationError(
                "temporary SES failure",
                code="ThrottlingException",
            )

    monkeypatch.setattr(
        notify,
        "parse_notification_record",
        lambda _record: context.message,
    )
    monkeypatch.setattr(notify, "_load_context", lambda _message: context)
    monkeypatch.setattr(notify, "database_session", fake_session)
    monkeypatch.setattr(
        notify.watchlist_ticker_crud,
        "investor_ids_watching",
        lambda *_args: investor_ids,
    )
    monkeypatch.setattr(notify, "_process_watcher", process_watcher)

    with pytest.raises(notify.RetryableNotificationError) as raised:
        notify._process_record(_sqs_record())

    assert raised.value.code == "ThrottlingException"
    assert processed == investor_ids


def test_missing_artifact_is_returned_as_a_batch_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The producer-consumer visibility race must not discard an alert."""
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = None
    db = MagicMock()
    db.execute.return_value = result

    @contextmanager
    def fake_session() -> Iterator[MagicMock]:
        yield db

    monkeypatch.setattr(notify, "database_session", fake_session)

    response = notify.handler(
        {"Records": [_sqs_record("artifact-not-visible")]},
        None,
    )

    assert response == {
        "batchItemFailures": [{"itemIdentifier": "artifact-not-visible"}]
    }


def test_signed_unsubscribe_url_never_contains_the_stored_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Email links may carry a signature, but never the signing key itself."""
    context = _context()
    token_hash = "b" * 64
    preferences = _preferences(unsubscribe_token_hash=token_hash)
    monkeypatch.setattr(
        settings,
        "FRONTEND_BASE_URL",
        "https://app.example.test",
        raising=False,
    )

    news_url, unsubscribe_url = notify._notification_urls(context, preferences)

    assert news_url == "https://app.example.test/ticker/BHP/news/"
    assert unsubscribe_url.startswith(
        "https://app.example.test/unsubscribe/?t=v1."
    )
    assert token_hash not in unsubscribe_url


def test_dry_run_verified_watcher_reaches_the_send_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry-run identity checks must support a complete local delivery flow."""
    context = _context()
    preferences = _preferences()
    lease = _lease(preferences.investor_id)
    sequence: list[str] = []

    def fake_claim(*_args: object) -> tuple[notify.DeliveryLease, None]:
        sequence.append("claim")
        return lease, None

    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", True, raising=False)
    monkeypatch.setattr(notify, "_load_preferences", lambda _id: preferences)
    monkeypatch.setattr(notify, "_claim_direct", fake_claim)
    monkeypatch.setattr(notify, "_over_run_cap", lambda *_args: False)
    monkeypatch.setattr(notify, "_at_daily_budget", lambda: False)
    monkeypatch.setattr(
        notify,
        "_preferences_still_current",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        notify,
        "render_alert_email",
        lambda **_kwargs: ("subject", "<p>html</p>", "text"),
    )
    monkeypatch.setattr(
        notify,
        "_send_rendered",
        lambda *_args, **_kwargs: sequence.append("send"),
    )

    notify._process_watcher(context, preferences.investor_id)

    assert notify.ses_alerts.identity_status(preferences.email) == "verified"
    assert sequence == ["claim", "send"]


@pytest.mark.parametrize("existing_status", ["claimed", "sent"])
def test_existing_direct_delivery_is_idempotently_skipped(
    monkeypatch: pytest.MonkeyPatch,
    existing_status: str,
) -> None:
    """A fresh claim or completed send must not result in another email."""
    context = _context()
    preferences = _preferences()
    send_rendered = Mock()
    monkeypatch.setattr(notify, "_load_preferences", lambda _id: preferences)
    monkeypatch.setattr(
        notify,
        "_claim_direct",
        lambda *_args: (None, existing_status),
    )
    monkeypatch.setattr(notify, "_send_rendered", send_rendered)

    notify._process_watcher(context, preferences.investor_id)

    send_rendered.assert_not_called()


def test_suppressed_direct_delivery_recovers_an_unsent_rollup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry after cap suppression must resume the rollup path."""
    context = _context()
    preferences = _preferences()
    ensure_rollup = Mock()
    monkeypatch.setattr(notify, "_load_preferences", lambda _id: preferences)
    monkeypatch.setattr(
        notify,
        "_claim_direct",
        lambda *_args: (None, "suppressed_cap"),
    )
    monkeypatch.setattr(notify, "_ensure_rollup", ensure_rollup)

    notify._process_watcher(context, preferences.investor_id)

    ensure_rollup.assert_called_once_with(
        context,
        preferences,
        identity_checked=False,
    )


def test_rollup_claim_uniqueness_skips_an_existing_sent_rollup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second suppression in one run must not send a second rollup."""
    context = _context()
    preferences = _preferences()
    send_rendered = Mock()
    monkeypatch.setattr(
        notify,
        "_claim_rollup",
        lambda *_args: (None, "rollup_sent"),
    )
    monkeypatch.setattr(notify, "_send_rendered", send_rendered)

    notify._ensure_rollup(context, preferences, identity_checked=True)

    send_rendered.assert_not_called()


def test_failed_rollup_claim_is_retried_and_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed rollup lease should resume without a new direct claim."""
    context = _context()
    preferences = _preferences()
    rollup_lease = _lease(preferences.investor_id, rollup=True)
    send_rendered = Mock()
    monkeypatch.setattr(
        notify,
        "_claim_rollup",
        lambda *_args: (rollup_lease, None),
    )
    monkeypatch.setattr(notify, "_at_daily_budget", lambda: False)
    monkeypatch.setattr(
        notify,
        "_preferences_still_current",
        lambda *_args: True,
    )
    monkeypatch.setattr(notify, "_suppressed_count", lambda *_args: 2)
    monkeypatch.setattr(
        notify,
        "render_rollup_email",
        lambda **_kwargs: ("rollup", "<p>html</p>", "text"),
    )
    monkeypatch.setattr(notify, "_send_rendered", send_rendered)

    notify._ensure_rollup(context, preferences, identity_checked=True)

    send_rendered.assert_called_once()


def test_per_run_cap_suppresses_direct_and_claims_one_rollup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The N+1th direct match should become a rollup, not another alert."""
    context = _context()
    preferences = _preferences()
    lease = _lease(preferences.investor_id)
    transition = Mock()
    ensure_rollup = Mock()
    monkeypatch.setattr(notify, "_load_preferences", lambda _id: preferences)
    monkeypatch.setattr(notify, "_claim_direct", lambda *_args: (lease, None))
    monkeypatch.setattr(notify, "_check_identity", lambda *_args: True)
    monkeypatch.setattr(notify, "_over_run_cap", lambda *_args: True)
    monkeypatch.setattr(notify, "_transition_delivery", transition)
    monkeypatch.setattr(notify, "_ensure_rollup", ensure_rollup)

    notify._process_watcher(context, preferences.investor_id)

    assert transition.call_args.args == (lease, "suppressed_cap")
    assert transition.call_args.kwargs["error_code"] == "per_run_cap"
    ensure_rollup.assert_called_once_with(
        context,
        preferences,
        identity_checked=True,
    )


def test_daily_budget_suppresses_without_retrying_or_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Budget exhaustion is a durable drop, not an SQS batch failure."""
    context = _context()
    preferences = _preferences()
    lease = _lease(preferences.investor_id)
    transition = Mock()
    send_rendered = Mock()
    monkeypatch.setattr(notify, "_load_preferences", lambda _id: preferences)
    monkeypatch.setattr(notify, "_claim_direct", lambda *_args: (lease, None))
    monkeypatch.setattr(notify, "_check_identity", lambda *_args: True)
    monkeypatch.setattr(notify, "_over_run_cap", lambda *_args: False)
    monkeypatch.setattr(notify, "_at_daily_budget", lambda: True)
    monkeypatch.setattr(notify, "_transition_delivery", transition)
    monkeypatch.setattr(notify, "_send_rendered", send_rendered)

    notify._process_watcher(context, preferences.investor_id)

    assert transition.call_args.args == (lease, "suppressed_budget")
    assert transition.call_args.kwargs["error_code"] == "daily_budget"
    send_rendered.assert_not_called()


def test_daily_budget_includes_the_current_claim_as_a_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current claim may send at the limit, but not above the limit."""
    db = object()
    count = Mock(return_value=5)

    @contextmanager
    def fake_session() -> Iterator[object]:
        yield db

    monkeypatch.setattr(settings, "ALERT_DAILY_BUDGET", 5, raising=False)
    monkeypatch.setattr(notify, "database_session", fake_session)
    monkeypatch.setattr(
        notify.alert_delivery_crud,
        "count_budget_commitments_last_24h",
        count,
    )

    assert notify._at_daily_budget() is False
    count.return_value = 6
    assert notify._at_daily_budget() is True


def test_handler_acknowledges_poison_messages() -> None:
    """A malformed message should leave SQS instead of cycling into the DLQ."""
    record = _sqs_record("poison-message")
    record["body"] = "not-json"

    assert notify.handler({"Records": [record]}, None) == {
        "batchItemFailures": []
    }


def test_handler_short_circuits_when_notifications_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dark-launch switch must stop work before any database or SES call."""
    process_record = Mock()
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False, raising=False)
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setattr(notify, "_process_record", process_record)

    assert notify.handler({"Records": [_sqs_record()]}, None) == {
        "batchItemFailures": []
    }
    process_record.assert_not_called()


def test_handler_returns_only_retryable_record_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failure must not cause successful siblings to be retried."""
    processed: list[str] = []

    def fake_handle(record: dict) -> None:
        processed.append(record["messageId"])
        if record["messageId"] == "retry-me":
            raise RuntimeError("temporary dependency failure")

    monkeypatch.setattr(notify, "_process_record", fake_handle)
    event = {
        "Records": [
            _sqs_record("first-success"),
            _sqs_record("retry-me"),
            _sqs_record("last-success"),
        ]
    }

    assert notify.handler(event, None) == {
        "batchItemFailures": [{"itemIdentifier": "retry-me"}]
    }
    assert processed == ["first-success", "retry-me", "last-success"]


def test_handler_does_not_expose_message_content_in_retry_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Failure logs may identify a record but must not leak queue contents."""
    private_value = "private-investor-address@example.com"
    record = _sqs_record("safe-correlation-id")
    record["body"] = json.dumps(
        {**_message_body(), "private": private_value}
    )
    monkeypatch.setattr(
        notify,
        "_process_record",
        Mock(side_effect=RuntimeError("temporary failure")),
    )

    assert notify.handler({"Records": [record]}, None) == {
        "batchItemFailures": [{"itemIdentifier": "safe-correlation-id"}]
    }
    assert private_value not in caplog.text


@pytest.mark.parametrize(
    ("outcome", "expected_status", "crud_method"),
    [
        ("sent", "sent", "mark_sent"),
        ("rejected", "rejected", "mark_rejected"),
        ("failed", "failed", "mark_failed"),
    ],
)
def test_delivery_and_subscription_outcomes_share_one_commit(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected_status: str,
    crud_method: str,
) -> None:
    """The ledger and D17 subscription mirror must commit atomically."""
    investor_id = uuid4()
    lease = _lease(investor_id)
    db = MagicMock()
    changed = SimpleNamespace(status=expected_status)
    delivery_write = Mock(return_value=changed)
    subscription_write = Mock(return_value=object())

    @contextmanager
    def fake_session() -> Iterator[MagicMock]:
        yield db

    monkeypatch.setattr(notify, "database_session", fake_session)
    monkeypatch.setattr(
        notify.alert_delivery_crud,
        crud_method,
        delivery_write,
    )
    monkeypatch.setattr(
        notify.alert_subscription_crud,
        "record_delivery_outcome",
        subscription_write,
    )

    kwargs: dict[str, str] = {}
    if outcome == "sent":
        kwargs["ses_message_id"] = "ses-message-id"
    else:
        kwargs["error_code"] = "MessageRejected"
    assert notify._transition_delivery(lease, outcome, **kwargs) == expected_status

    assert delivery_write.call_args.kwargs["commit"] is False
    assert subscription_write.call_args.kwargs["commit"] is False
    assert subscription_write.call_args.kwargs["investor_id"] == investor_id
    assert subscription_write.call_args.kwargs["delivery_status"] == expected_status
    db.commit.assert_called_once_with()


def test_live_verification_correction_and_rejection_share_one_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SES disagreement must correct preferences with the rejection ledger row."""
    preferences = _preferences()
    lease = _lease(preferences.investor_id)
    db = MagicMock()
    verification_write = Mock(return_value=object())
    rejection_write = Mock(return_value=SimpleNamespace(status="rejected"))
    subscription_write = Mock(return_value=object())

    @contextmanager
    def fake_session() -> Iterator[MagicMock]:
        yield db

    monkeypatch.setattr(notify, "database_session", fake_session)
    monkeypatch.setattr(
        notify.alert_subscription_crud,
        "update_verification_state",
        verification_write,
    )
    monkeypatch.setattr(
        notify.alert_delivery_crud,
        "mark_rejected",
        rejection_write,
    )
    monkeypatch.setattr(
        notify.alert_subscription_crud,
        "record_delivery_outcome",
        subscription_write,
    )

    notify._reject_with_identity_correction(lease, preferences, "pending")

    assert verification_write.call_args.kwargs["commit"] is False
    assert verification_write.call_args.kwargs["expected_email"] == preferences.email
    assert (
        verification_write.call_args.kwargs["expected_verification_status"]
        == "verified"
    )
    assert rejection_write.call_args.kwargs["commit"] is False
    assert subscription_write.call_args.kwargs["commit"] is False
    db.commit.assert_called_once_with()


def test_ses_success_marks_the_delivery_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A returned SES message ID should become the final ledger outcome."""
    lease = _lease(uuid4())
    transition = Mock()
    monkeypatch.setattr(
        notify,
        "_send_alert",
        Mock(return_value="ses-message-123"),
    )
    monkeypatch.setattr(notify, "_transition_delivery", transition)

    notify._send_rendered(
        lease,
        _preferences(investor_id=lease.investor_id),
        ("subject", "<p>html</p>", "text"),
        "https://app.example.test/unsubscribe/?token=signed",
    )

    transition.assert_called_once_with(
        lease,
        "sent",
        ses_message_id="ses-message-123",
    )


def test_terminal_ses_rejection_is_recorded_and_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MessageRejected is terminal and must not return to SQS."""
    lease = _lease(uuid4())
    transition = Mock()
    monkeypatch.setattr(
        notify,
        "_send_alert",
        Mock(side_effect=_client_error("MessageRejected")),
    )
    monkeypatch.setattr(notify, "_transition_delivery", transition)

    notify._send_rendered(
        lease,
        _preferences(investor_id=lease.investor_id),
        ("subject", "<p>html</p>", "text"),
        "https://app.example.test/unsubscribe/?token=signed",
    )

    assert transition.call_args.args == (lease, "rejected")
    assert transition.call_args.kwargs["error_code"] == "MessageRejected"


def test_retryable_ses_throttle_is_recorded_before_batch_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Throttling must release the claim as failed, then retry that record."""
    lease = _lease(uuid4())
    transition = Mock(return_value="failed")
    monkeypatch.setattr(
        notify,
        "_send_alert",
        Mock(side_effect=_client_error("ThrottlingException")),
    )
    monkeypatch.setattr(notify, "_transition_delivery", transition)

    with pytest.raises(notify.RetryableNotificationError) as raised:
        notify._send_rendered(
            lease,
            _preferences(investor_id=lease.investor_id),
            ("subject", "<p>html</p>", "text"),
            "https://app.example.test/unsubscribe/?token=signed",
        )

    assert raised.value.code == "ThrottlingException"
    assert transition.call_args.args == (lease, "failed")
    assert transition.call_args.kwargs["error_code"] == "ThrottlingException"


def test_temporary_identity_failure_retries_without_downgrading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SES TEMPORARY_FAILURE must not become a durable pending state."""
    preferences = _preferences()
    lease = _lease(preferences.investor_id)
    transition = Mock(return_value="failed")
    correction = Mock()
    monkeypatch.setattr(
        notify.ses_alerts,
        "identity_status",
        lambda _email: "temporary_failure",
    )
    monkeypatch.setattr(notify, "_transition_delivery", transition)
    monkeypatch.setattr(
        notify,
        "_reject_with_identity_correction",
        correction,
    )

    with pytest.raises(notify.RetryableNotificationError) as raised:
        notify._check_identity(lease, preferences)

    assert raised.value.code == "ses_identity_temporary_failure"
    assert transition.call_args.args == (lease, "failed")
    correction.assert_not_called()


def test_live_send_limiter_spaces_fanout_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reserved concurrency alone must not exceed the one-send rate."""
    sleep = Mock()
    send = Mock(return_value="ses-message-id")
    monotonic = Mock(side_effect=[10.25, 11.25])
    monkeypatch.setattr(settings, "NOTIFICATIONS_DRY_RUN", False, raising=False)
    monkeypatch.setattr(notify, "_LAST_LIVE_SEND_AT", 10.0)
    monkeypatch.setattr(notify.time, "monotonic", monotonic)
    monkeypatch.setattr(notify.time, "sleep", sleep)
    monkeypatch.setattr(notify.ses_alerts, "send_alert", send)

    result = notify._send_alert(
        to="investor@example.com",
        subject="subject",
        html="<p>html</p>",
        text_body="text",
        unsubscribe_url="https://app.example.test/unsubscribe/?token=signed",
    )

    assert result == "ses-message-id"
    sleep.assert_called_once_with(0.75)
    send.assert_called_once()


def test_api_image_packages_the_notification_worker() -> None:
    """The shared API image must contain the Lambda module named in SAM."""
    dockerfile = (
        REPOSITORY_ROOT / "backend" / "Dockerfile.api"
    ).read_text(encoding="utf-8")

    lambda_copy = next(
        line for line in dockerfile.splitlines() if line.startswith("COPY lambdas/")
    )
    assert "lambdas/notify.py" in lambda_copy
    assert "requirements-analysis.txt" not in dockerfile


def test_runtime_configuration_load_precedes_configured_imports() -> None:
    """Cold starts must resolve SSM before settings and DB code are imported."""
    source = (
        REPOSITORY_ROOT / "backend" / "lambdas" / "notify.py"
    ).read_text(encoding="utf-8")

    load_position = source.index("\nload_runtime_configuration()\n")
    settings_position = source.index("\nfrom app.core.config import settings")
    ses_position = source.index("\nfrom app.services import ses_alerts")

    assert load_position < settings_position < ses_position
