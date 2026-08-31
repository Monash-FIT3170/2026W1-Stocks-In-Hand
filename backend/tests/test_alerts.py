"""Phase 9 acceptance contracts for local watchlist alerts."""

# pylint: disable=protected-access,too-many-locals,wrong-import-position

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.api.routes import notification_preferences
from app.core.config import settings
from app.crud import alert_delivery as alert_delivery_crud
from app.schemas.notification import UnsubscribeRequest
from app.services.alert_templates import render_alert_email
from lambdas import analysis, notify


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class _CapturedResult:
    """Represent a claim that did not acquire a database row."""

    def scalar_one_or_none(self) -> None:
        """Return no claimed row from the captured statement."""
        return None


class _CapturedSession:
    """Capture PostgreSQL claim SQL without requiring a running database."""

    def __init__(self, scrape_run_id: UUID) -> None:
        self.scrape_run_id = scrape_run_id
        self.statement: Any | None = None
        self.commit_count = 0

    def scalar(self, statement: Any) -> UUID:
        """Return the artifact provenance expected by the claim helper."""
        self.statement = statement
        return self.scrape_run_id

    def execute(self, statement: Any) -> _CapturedResult:
        """Capture the generated PostgreSQL insert statement."""
        self.statement = statement
        return _CapturedResult()

    def commit(self) -> None:
        """Record the claim helper's durable transaction boundary."""
        self.commit_count += 1


@pytest.fixture(autouse=True)
def _enabled_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True, raising=False)
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")


def _context() -> notify.NotificationContext:
    message = notify.NotificationMessage.model_validate(
        {
            "schema_version": 1,
            "artifact_id": str(uuid4()),
            "ticker": "BHP",
            "scrape_run_id": str(uuid4()),
            "sentiment_label": "negative",
            "confidence_score": "0.82",
        }
    )
    return notify.NotificationContext(
        message=message,
        ticker_id=uuid4(),
        ticker_symbol="BHP",
        company_name="BHP Group Limited",
        artifact_title="Half year results",
        summary_text=None,
        sentiment_label="negative",
        confidence_score=message.confidence_score,
    )


def _preferences() -> notify.WatcherPreferences:
    return notify.WatcherPreferences(
        investor_id=uuid4(),
        subscription_id=uuid4(),
        email="investor@example.com",
        enabled=True,
        verification_status="verified",
        verification_requested_at=datetime.now(timezone.utc),
        unsubscribe_token_hash="a" * 64,
        rule=notify.RulePreferences(
            id=uuid4(),
            enabled=True,
            rule_type="sentiment_threshold",
            sentiment_labels=("negative",),
            min_confidence=Decimal("0.75"),
        ),
    )


def _lease(investor_id: UUID, *, rollup: bool = False) -> notify.DeliveryLease:
    return notify.DeliveryLease(
        id=uuid4(),
        investor_id=investor_id,
        claimed_at=datetime.now(timezone.utc),
        rollup=rollup,
    )


def _message_rejected() -> notify.brevo_alerts.BrevoApiError:
    return notify.brevo_alerts.BrevoApiError(
        status_code=400,
        code="invalid_parameter",
    )


def test_compose_files_keep_brevo_delivery_in_dry_run_by_default() -> None:
    """Local stacks must not send real Brevo messages by default."""
    if not (REPOSITORY_ROOT / "docker-compose-dev.yml").is_file():
        pytest.skip("Repository-level compose files are outside this test image")

    for filename in ("docker-compose-dev.yml", "docker-compose-tests.yml"):
        source = (REPOSITORY_ROOT / filename).read_text(encoding="utf-8")
        assert "NOTIFICATIONS_DRY_RUN" in source
        assert "BREVO_API_KEY" in source
        assert "localstack/localstack" not in source
        assert "AWS_ENDPOINT_URL_SES" not in source


def test_rule_matching_covers_label_and_confidence_boundaries() -> None:
    """A matching label fires at the threshold, but never below it."""
    rule = SimpleNamespace(
        enabled=True,
        sentiment_labels=["negative"],
        min_confidence=Decimal("0.75"),
    )
    assert notify._rule_matches(rule, "negative", Decimal("0.75")) is True
    assert notify._rule_matches(rule, "negative", Decimal("0.7499")) is False
    assert notify._rule_matches(rule, "positive", Decimal("0.99")) is False


def test_duplicate_delivery_is_skipped_without_a_second_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed investor and artifact claim must remain idempotent."""
    context = _context()
    preferences = _preferences()
    send = Mock()
    monkeypatch.setattr(notify, "_load_preferences", lambda _id: preferences)
    monkeypatch.setattr(notify, "_claim_direct", lambda *_args: (None, "sent"))
    monkeypatch.setattr(notify, "_send_rendered", send)

    notify._process_watcher(context, preferences.investor_id)

    send.assert_not_called()


def test_claim_sql_allows_failed_or_stale_takeover() -> None:
    """Fresh claims stay protected while stale or failed claims can retry."""
    scrape_run_id = uuid4()
    db = _CapturedSession(scrape_run_id)

    alert_delivery_crud.claim(
        db,
        uuid4(),
        uuid4(),
        scrape_run_id,
        stale_after_minutes=15,
    )

    sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (investor_id, artifact_id) DO UPDATE" in sql
    assert "alert_deliveries.status = %(status_1)s" in sql
    assert "alert_deliveries.claimed_at < now() -" in sql
    assert db.commit_count == 1


def test_per_run_cap_suppresses_direct_and_requests_one_rollup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The next direct alert becomes one rollup after the per-run cap."""
    context = _context()
    preferences = _preferences()
    lease = _lease(preferences.investor_id)
    transition = Mock()
    rollup = Mock()
    monkeypatch.setattr(notify, "_load_preferences", lambda _id: preferences)
    monkeypatch.setattr(notify, "_claim_direct", lambda *_args: (lease, None))
    monkeypatch.setattr(
        notify,
        "_check_recipient_confirmation",
        lambda *_args: True,
    )
    monkeypatch.setattr(notify, "_over_run_cap", lambda *_args: True)
    monkeypatch.setattr(notify, "_transition_delivery", transition)
    monkeypatch.setattr(notify, "_ensure_rollup", rollup)

    notify._process_watcher(context, preferences.investor_id)

    assert transition.call_args.args == (lease, "suppressed_cap")
    rollup.assert_called_once_with(
        context,
        preferences,
        confirmation_checked=True,
    )


def test_existing_rollup_prevents_a_second_rollup_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two suppressions in one run must share the partial-index rollup row."""
    context = _context()
    preferences = _preferences()
    send = Mock()
    monkeypatch.setattr(
        notify,
        "_claim_rollup",
        lambda *_args: (None, "rollup_sent"),
    )
    monkeypatch.setattr(notify, "_send_rendered", send)

    notify._ensure_rollup(context, preferences, confirmation_checked=True)

    send.assert_not_called()


def test_daily_budget_suppresses_without_send_or_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Budget exhaustion records a terminal suppression without Brevo."""
    context = _context()
    preferences = _preferences()
    lease = _lease(preferences.investor_id)
    transition = Mock()
    send = Mock()
    monkeypatch.setattr(notify, "_load_preferences", lambda _id: preferences)
    monkeypatch.setattr(notify, "_claim_direct", lambda *_args: (lease, None))
    monkeypatch.setattr(
        notify,
        "_check_recipient_confirmation",
        lambda *_args: True,
    )
    monkeypatch.setattr(notify, "_over_run_cap", lambda *_args: False)
    monkeypatch.setattr(notify, "_at_daily_budget", lambda: True)
    monkeypatch.setattr(notify, "_transition_delivery", transition)
    monkeypatch.setattr(notify, "_send_rendered", send)

    notify._process_watcher(context, preferences.investor_id)

    assert transition.call_args.args == (lease, "suppressed_budget")
    assert transition.call_args.kwargs["error_code"] == "daily_budget"
    send.assert_not_called()


def test_terminal_brevo_error_updates_ledger_and_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal provider error must update both outcome records and stop."""
    preferences = _preferences()
    lease = _lease(preferences.investor_id)
    db = MagicMock()
    rejected = Mock(return_value=SimpleNamespace(status="rejected"))
    mirrored = Mock(return_value=object())

    @contextmanager
    def fake_session() -> Iterator[MagicMock]:
        yield db

    monkeypatch.setattr(notify, "database_session", fake_session)
    monkeypatch.setattr(notify, "_send_alert", Mock(side_effect=_message_rejected()))
    monkeypatch.setattr(notify.alert_delivery_crud, "mark_rejected", rejected)
    monkeypatch.setattr(
        notify.alert_subscription_crud,
        "record_delivery_outcome",
        mirrored,
    )

    notify._send_rendered(
        lease,
        preferences,
        ("subject", "<p>html</p>", "text"),
        "https://app.example.test/unsubscribe/?t=signed",
    )

    assert rejected.call_args.args[3] == "invalid_parameter"
    assert mirrored.call_args.kwargs["delivery_status"] == "rejected"
    assert mirrored.call_args.kwargs["error_code"] == "invalid_parameter"
    db.commit.assert_called_once_with()


def test_template_renders_when_summary_is_null() -> None:
    """A missing optional summary must not block multipart rendering."""
    subject, html, text = render_alert_email(
        ticker_symbol="BHP",
        company_name="BHP Group Limited",
        artifact_title="Half year results",
        summary_text=None,
        sentiment_label="negative",
        confidence_score=Decimal("0.82"),
        news_url="https://app.example.test/ticker/BHP/news/",
        unsubscribe_url="https://app.example.test/unsubscribe/?t=signed",
    )
    assert subject
    assert "Half year results" in html
    assert "Half year results" in text
    assert "No summary available" not in html


def test_unsubscribe_valid_and_invalid_tokens_share_the_public_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public endpoint disables a match without becoming an oracle."""
    raw_token = "phase-nine-unsubscribe-token-value"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    subscription = SimpleNamespace(
        id=uuid4(),
        unsubscribe_token_hash=token_hash,
    )
    disable = Mock()
    monkeypatch.setattr(
        notification_preferences.alert_subscription_crud,
        "get_subscription_by_unsubscribe_token_hash",
        lambda _db, value: subscription if value == token_hash else None,
    )
    monkeypatch.setattr(
        notification_preferences.alert_subscription_crud,
        "disable_subscription",
        disable,
    )
    db = MagicMock()

    valid = notification_preferences.unsubscribe_notifications(
        UnsubscribeRequest(token=raw_token),
        db=db,
    )
    invalid = notification_preferences.unsubscribe_notifications(
        UnsubscribeRequest(token="invalid-phase-nine-token"),
        db=db,
    )

    assert valid.message == invalid.message
    disable.assert_called_once()


def test_producer_absorbs_notification_publish_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A notification queue outage must never fail stored analysis work."""
    publish = Mock(side_effect=RuntimeError("queue unavailable"))
    monkeypatch.setattr(analysis, "_publish_notification", publish)

    analysis._try_publish_notification(
        artifact_id=uuid4(),
        ticker="BHP",
        scrape_run_id=uuid4(),
        sentiment={"sentiment_label": "negative", "confidence_score": 0.82},
        correlation="phase-nine",
        attempt=1,
    )

    publish.assert_called_once()
