"""Every alert layer accepts the same sentiment labels.

Neutral-only rules used to be accepted by the settings page, the preferences
schema and rule validation, then dropped by the analysis producer and rejected
by NotificationMessage, so they never fired.
"""

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alert_vocabulary import ALERT_SENTIMENT_LABELS
from app.crud.alert_rule import KNOWN_SENTIMENT_LABELS
from app.messages import NotificationMessage
from app.schemas.notification import NotificationPreferencesUpdate
from lambdas import analysis

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("label", sorted(ALERT_SENTIMENT_LABELS))
def test_producer_publishes_every_alertable_label(
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    publish = MagicMock()
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setattr(analysis, "_publish_notification", publish)

    analysis._try_publish_notification(
        artifact_id=uuid4(),
        ticker="CSL",
        scrape_run_id=uuid4(),
        sentiment={"sentiment_label": label, "confidence_score": 0.9},
        correlation="message-1",
        attempt=1,
    )

    publish.assert_called_once()


@pytest.mark.parametrize("label", sorted(ALERT_SENTIMENT_LABELS))
def test_notification_message_accepts_every_alertable_label(label: str) -> None:
    message = NotificationMessage(
        artifact_id=uuid4(),
        ticker="CSL",
        scrape_run_id=uuid4(),
        sentiment_label=label,
        confidence_score="0.9",
    )

    assert message.sentiment_label == label


def test_notification_message_rejects_unknown_labels() -> None:
    with pytest.raises(ValidationError):
        NotificationMessage(
            artifact_id=uuid4(),
            ticker="CSL",
            scrape_run_id=uuid4(),
            sentiment_label="mixed",
            confidence_score="0.9",
        )


def test_api_and_rule_validation_share_the_vocabulary() -> None:
    update = NotificationPreferencesUpdate(
        enabled=True,
        sentiment_labels=sorted(ALERT_SENTIMENT_LABELS),
    )

    assert set(update.sentiment_labels) == ALERT_SENTIMENT_LABELS
    assert KNOWN_SENTIMENT_LABELS == ALERT_SENTIMENT_LABELS
    assert NotificationPreferencesUpdate(enabled=True).sentiment_labels == ["negative"]


def test_settings_page_offers_exactly_the_alertable_labels() -> None:
    page = (
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "app"
        / "settings"
        / "notifications"
        / "page.jsx"
    ).read_text(encoding="utf-8")
    options = page.split("const SENTIMENT_OPTIONS = [", 1)[1].split("]", 1)[0]

    assert set(re.findall(r'value: "([a-z]+)"', options)) == ALERT_SENTIMENT_LABELS
