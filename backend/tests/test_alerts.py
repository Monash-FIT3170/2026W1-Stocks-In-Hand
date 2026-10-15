"""Phase 9 acceptance contracts for local watchlist alerts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.services.alert_templates import render_alert_email


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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
