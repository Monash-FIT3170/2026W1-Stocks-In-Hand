"""Every alert layer uses the same alert vocabulary.

Neutral-only rules used to be accepted by the settings page, the preferences
schema and rule validation, then dropped by the analysis producer and rejected
by NotificationMessage, so they never fired. The settings page is checked
against the vocabulary's labels, verification statuses and delivery problem
statuses.
"""

import re
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alert_vocabulary import (
    ALERT_SENTIMENT_LABELS,
    DEFAULT_ALERT_MIN_CONFIDENCE,
    DELIVERY_PROBLEM_STATUSES,
    VerificationStatus,
)
from app.crud.alert_rule import KNOWN_SENTIMENT_LABELS
from app.messages import NotificationMessage
from app.models.alert_rule import AlertRule
from app.schemas.notification import NotificationPreferencesUpdate

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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


def test_a_new_rule_wants_the_vocabulary_threshold() -> None:
    assert NotificationPreferencesUpdate(enabled=True).min_confidence == float(
        DEFAULT_ALERT_MIN_CONFIDENCE
    )
    assert AlertRule.__table__.c.min_confidence.default.arg == DEFAULT_ALERT_MIN_CONFIDENCE


def _settings_page() -> str:
    return (
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "app"
        / "settings"
        / "notifications"
        / "page.jsx"
    ).read_text(encoding="utf-8")


def test_settings_page_offers_exactly_the_alertable_labels() -> None:
    options = _settings_page().split("const SENTIMENT_OPTIONS = [", 1)[1].split("]", 1)[0]

    assert set(re.findall(r'value: "([a-z]+)"', options)) == ALERT_SENTIMENT_LABELS


def test_settings_page_has_copy_for_exactly_the_verification_statuses() -> None:
    copy = _settings_page().split("const VERIFICATION_COPY = {", 1)[1].split("\n}\n", 1)[0]

    assert set(re.findall(r"^  ([a-z_]+): \{", copy, re.MULTILINE)) == set(
        VerificationStatus
    )


def test_settings_page_reports_exactly_the_delivery_problem_statuses() -> None:
    statuses = _settings_page().split("const DELIVERY_PROBLEM_STATUSES = [", 1)[1]

    assert set(re.findall(r'"([a-z_]+)"', statuses.split("]", 1)[0])) == (
        DELIVERY_PROBLEM_STATUSES
    )
