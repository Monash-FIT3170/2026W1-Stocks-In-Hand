"""Stored category sentiment: bucket keywords and confidence weighting."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes.category_sentiment import (
    _aggregate_stored_category,
    _categories_for_stored_artifact,
)


def _announcement(title: str, *, artifact_type: str = "asx_announcement_other", **metadata):
    return SimpleNamespace(
        source_type="asx_announcement",
        artifact_type=artifact_type,
        title=title,
        artifact_metadata=metadata,
    )


def _sentiment(label: str, confidence):
    return SimpleNamespace(
        sentiment_label=label,
        confidence_score=confidence,
        model_used="ProsusAI/finbert",
        created_at=None,
    )


def test_security_notifications_are_not_filed_under_risk() -> None:
    notice = _announcement(
        "Notification regarding unquoted securities - CSL",
        artifact_type="security_notification",
        category="SecurityNotification",
    )

    assert "risk" not in _categories_for_stored_artifact(notice)


@pytest.mark.parametrize(
    ("title", "bucket"),
    [
        ("Cyber security incident update", "risk"),
        ("Impairment of goodwill", "risk"),
        ("Dividends declared for the half year", "dividend"),
        ("Appointment of directors", "organisational"),
        ("Share buy-back completed", "dividend"),
        ("Profit declined in the quarter", "risk"),
    ],
)
def test_keywords_still_match_whole_words_and_inflections(title: str, bucket: str) -> None:
    assert bucket in _categories_for_stored_artifact(_announcement(title))


def test_keywords_do_not_match_inside_other_words() -> None:
    preview = _announcement("Investor day preview and asterisked notes")

    assert _categories_for_stored_artifact(preview) == ["strategy"]


def test_missing_or_zero_confidence_adds_no_weight() -> None:
    artifact = _announcement("Half year results")
    rows = [
        (artifact, _sentiment("positive", 0.9)),
        (artifact, _sentiment("negative", 0)),
        (artifact, _sentiment("negative", None)),
    ]

    result = _aggregate_stored_category("revenue", rows)

    assert result["sentiment_label"] == "positive"
    assert result["distribution"] == {"positive": 1.0, "neutral": 0.0, "negative": 0.0}


def test_rows_without_any_confidence_are_counted_equally() -> None:
    artifact = _announcement("Half year results")
    rows = [
        (artifact, _sentiment("negative", None)),
        (artifact, _sentiment("negative", 0)),
        (artifact, _sentiment("positive", None)),
    ]

    result = _aggregate_stored_category("revenue", rows)

    assert result["sentiment_label"] == "negative"
    assert result["distribution"]["negative"] == pytest.approx(0.6667, abs=1e-4)
