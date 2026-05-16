"""Tests for the database-backed announcements feed mapping."""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crud.announcement import _announcement_from_artifact, _sydney_day_bounds
from app.models.artifact import Artifact
from app.models.ticker import Ticker


def test_announcement_mapping_uses_metadata_and_ticker_symbol() -> None:
    ticker = Ticker(symbol="BHP", company_name="BHP Group", exchange="ASX")
    artifact = Artifact(
        id=uuid.uuid4(),
        ticker=ticker,
        source_type="asx_announcement",
        artifact_type="dividend_announcement",
        title="Dividend update",
        url="https://example.test/asx/bhp",
        raw_text="Raw announcement text",
        published_at=datetime(2026, 5, 16, 10, 30, tzinfo=timezone.utc),
        artifact_metadata={
            "category": "DividendAnnouncement",
            "about": "Dividend details for shareholders.",
            "changed": "The declared dividend increased.",
            "matters": "This affects shareholder income expectations.",
        },
    )

    result = _announcement_from_artifact(artifact)

    assert result.ticker == "BHP"
    assert result.tag == "Dividend Announcement"
    assert result.title == "Dividend update"
    assert result.about == "Dividend details for shareholders."
    assert result.changed == "The declared dividend increased."
    assert result.matters == "This affects shareholder income expectations."
    assert result.url == "https://example.test/asx/bhp"


def test_announcement_mapping_has_safe_fallbacks_for_missing_metadata() -> None:
    artifact = Artifact(
        id=uuid.uuid4(),
        source_type="asx_announcement",
        artifact_type="asx_announcement_other",
        title="General update",
        raw_text=" ".join(["Long raw text"] * 40),
        created_at=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc),
        artifact_metadata={"category": "UNKNOWN", "pdf_url": "https://example.test/file.pdf"},
    )

    result = _announcement_from_artifact(artifact)

    assert result.ticker == "ASX"
    assert result.tag == "Asx Announcement Other"
    assert result.about.startswith("Long raw text")
    assert result.about.endswith("...")
    assert result.changed == "No change summary available yet."
    assert result.matters == "No impact summary available yet."
    assert result.url == "https://example.test/file.pdf"


def test_sydney_day_bounds_match_melbourne_calendar_day() -> None:
    now = datetime(2026, 5, 16, 14, 30, tzinfo=timezone.utc)

    start, end = _sydney_day_bounds(now)

    assert start.isoformat() == "2026-05-17T00:00:00+10:00"
    assert end.isoformat() == "2026-05-18T00:00:00+10:00"
