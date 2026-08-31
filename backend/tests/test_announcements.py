"""Tests for the database-backed announcements feed mapping."""

import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes import announcement as announcement_routes
from app.crud.announcement import (
    _announcement_from_artifact,
    _sydney_date_end,
    _sydney_date_start,
    _sydney_day_bounds,
    get_announcements,
)
from app.models.artifact import Artifact
from app.models.artifact_summary import ArtifactSummary
from app.models.ticker import Ticker


def test_announcements_route_accepts_path_without_trailing_slash(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(announcement_routes.router)
    app.dependency_overrides[announcement_routes.get_db] = lambda: None
    monkeypatch.setattr(announcement_routes.crud, "get_announcements", lambda *_args, **_kwargs: [])

    response = TestClient(app).get("/announcements", follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == []


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


def test_announcement_mapping_uses_summary_metadata_as_about_fallback() -> None:
    artifact = Artifact(
        id=uuid.uuid4(),
        source_type="asx_announcement",
        artifact_type="asx_announcement_other",
        title="Trading update",
        raw_text="Raw announcement text",
        artifact_metadata={
            "summary": "The company released a concise generated summary.",
            "changed": "No material change identified.",
            "matters": "Investors can use this as a quick filing overview.",
        },
    )

    result = _announcement_from_artifact(artifact)

    assert result.about == "The company released a concise generated summary."
    assert result.changed == "No material change identified."
    assert result.matters == "Investors can use this as a quick filing overview."


def test_announcement_mapping_recovers_legacy_combined_bedrock_summary() -> None:
    artifact = Artifact(
        id=uuid.uuid4(),
        source_type="asx_announcement",
        artifact_type="asx_announcement_other",
        title="Community grants update",
        raw_text="Raw PDF header text",
        artifact_metadata={"category": "UNKNOWN"},
    )
    artifact.summaries.append(
        ArtifactSummary(
            summary_text=(
                "Woodside awarded community grants.\n\n"
                "The filing covers local community funding.\n\n"
                "A new grant round was announced.\n\n"
                "The investment may support Woodside's social licence."
            ),
            model_used="bedrock:openai.gpt-oss-120b-1:0",
        )
    )

    result = _announcement_from_artifact(artifact)

    assert result.about == "The filing covers local community funding."
    assert result.changed == "A new grant round was announced."
    assert result.matters == (
        "The investment may support Woodside's social licence."
    )


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


def test_custom_date_bounds_use_sydney_calendar_days() -> None:
    start = _sydney_date_start(date(2026, 5, 1))
    end = _sydney_date_end(date(2026, 5, 16))

    assert start.isoformat() == "2026-05-01T00:00:00+10:00"
    assert end.isoformat() == "2026-05-17T00:00:00+10:00"


def test_announcement_feed_uses_stable_secondary_id_ordering() -> None:
    class QueryStub:
        def __init__(self) -> None:
            self.ordering = ()

        def options(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def order_by(self, *ordering):
            self.ordering = ordering
            return self

        def offset(self, _offset):
            return self

        def limit(self, _limit):
            return self

        def all(self):
            return []

    class DbStub:
        def __init__(self) -> None:
            self.query_stub = QueryStub()

        def query(self, _model):
            return self.query_stub

    db = DbStub()

    assert get_announcements(db) == []
    assert len(db.query_stub.ordering) == 2
    assert str(db.query_stub.ordering[1]) == "artifacts.id DESC"
