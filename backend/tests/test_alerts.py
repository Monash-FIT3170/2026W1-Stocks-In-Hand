"""Phase 9 acceptance contracts for local watchlist alerts."""

# pylint: disable=protected-access,too-many-locals,wrong-import-position

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from app.api.routes import notification_preferences
from app.core.config import settings
from app.schemas.notification import UnsubscribeRequest
from app.services.alert_templates import render_alert_email
from lambdas import analysis


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _enabled_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True, raising=False)
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")


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
