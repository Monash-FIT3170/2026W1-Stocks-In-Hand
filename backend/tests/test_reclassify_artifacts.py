from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools.reclassify_artifacts import (
    ReclassificationOptions,
    reclassify_records,
)
from app.read_models.ticker_sentiment import buckets_for


def _artifact(
    *,
    artifact_id: int,
    ticker: str,
    title: str,
    raw_text: str,
    metadata: dict | None = None,
    source_type: str = "asx_announcement",
    artifact_type: str = "asx_announcement_other",
):
    return SimpleNamespace(
        id=artifact_id,
        ticker=SimpleNamespace(symbol=ticker),
        title=title,
        raw_text=raw_text,
        source_type=source_type,
        artifact_type=artifact_type,
        source_adapter=ticker.lower(),
        document_url=f"https://example.test/{artifact_id}.pdf",
        s3_key=None,
        artifact_metadata=metadata or {},
    )


def test_dry_run_respects_ticker_and_row_limit_without_mutation() -> None:
    csl = _artifact(
        artifact_id=1,
        ticker="CSL",
        title="Appendix 4D and Interim Financial Report",
        raw_text="Appendix 4D. Half year report for the six months ended.",
        metadata={"custom": "preserved"},
    )
    anz = _artifact(
        artifact_id=2,
        ticker="ANZ",
        title="Dividend Announcement",
        raw_text="The board declared a dividend of 18 cents per share.",
    )
    later_csl = _artifact(
        artifact_id=3,
        ticker="CSL",
        title="Annual Report",
        raw_text="Annual report with audited financial statements.",
    )
    before = deepcopy(csl.artifact_metadata)

    summary = reclassify_records(
        [csl, anz, later_csl],
        ReclassificationOptions(
            dry_run=True,
            ticker="csl",
            batch_size=10,
            limit=1,
        ),
    )

    assert summary.scanned == 1
    assert summary.changed == 1
    assert summary.failed == 0
    assert csl.artifact_metadata == before
    assert anz.artifact_metadata == {}
    assert later_csl.artifact_metadata == {}


def test_applied_reclassification_is_idempotent_and_preserves_analysis() -> None:
    artifact = _artifact(
        artifact_id=1,
        ticker="CSL",
        title="Q2 Trading and Guidance Update",
        raw_text="Quarterly sales for the quarter and revised earnings guidance.",
        metadata={
            "about": "Existing summary",
            "sentiment_label": "neutral",
            "category": "QuarterlyTradingUpdate",
            "extracted_data": {"sales": "$20m"},
        },
    )
    options = ReclassificationOptions(dry_run=False, batch_size=10, limit=10)

    first = reclassify_records([artifact], options)
    second = reclassify_records([artifact], options)

    assert first.changed == 1
    assert first.ambiguous == 1
    assert second.changed == 0
    assert second.unchanged == 1
    assert artifact.artifact_metadata["category"] == "UNKNOWN"
    assert artifact.artifact_metadata["classification"]["status"] == "needs_review"
    assert artifact.artifact_metadata["extracted_data"] == {"sales": "$20m"}
    assert artifact.artifact_metadata["extracted_data_stale"] is True
    assert artifact.artifact_metadata["about"] == "Existing summary"
    assert artifact.artifact_metadata["sentiment_label"] == "neutral"


def test_reclassification_stores_an_announcements_category_type() -> None:
    dividend = (
        "The board declared a dividend of 83 cents per share. "
        "Record date 10 March 2026. Payment date 2 April 2026."
    )
    announcement = _artifact(
        artifact_id=1,
        ticker="CSL",
        title="Interim Dividend",
        raw_text=dividend,
    )
    story = _artifact(
        artifact_id=2,
        ticker="CSL",
        title="Interim Dividend",
        raw_text=dividend,
        source_type="news",
        artifact_type="news_article",
    )
    unapplied = _artifact(
        artifact_id=3,
        ticker="CSL",
        title="Interim Dividend",
        raw_text=dividend,
    )

    reclassify_records(
        [announcement, story],
        ReclassificationOptions(dry_run=False, batch_size=10, limit=10),
    )
    reclassify_records(
        [unapplied],
        ReclassificationOptions(dry_run=True, batch_size=10, limit=10),
    )

    assert announcement.artifact_metadata["category"] == "DividendAnnouncement"
    assert announcement.artifact_type == "dividend_announcement"
    assert "classification" in story.artifact_metadata
    assert story.artifact_type == "news_article"
    assert unapplied.artifact_type == "asx_announcement_other"


def test_an_older_appendix_2a_is_reclassified_once_without_rewriting_its_analysis() -> None:
    artifact = _artifact(
        artifact_id=1,
        ticker="ANZ",
        title="Application for quotation of securities - ANZ",
        raw_text="Appendix 2A\nTotal number of +securities on issue.",
        metadata={
            "category": "UNKNOWN",
            "classification": {"classifier_version": "rules-v2", "status": "unknown"},
            "summary": "Previously stored summary.",
            "sentiment_label": "neutral",
            "custom": {"preserved": True},
        },
    )
    original = deepcopy(artifact.artifact_metadata)
    preview = reclassify_records([artifact], ReclassificationOptions())

    assert preview.changed == 1
    assert artifact.artifact_metadata == original
    assert artifact.artifact_type == "asx_announcement_other"

    applied = reclassify_records([artifact], ReclassificationOptions(dry_run=False))
    repeated = reclassify_records([artifact], ReclassificationOptions(dry_run=False))

    assert applied.changed == 1 and applied.failed == 0
    assert repeated.changed == 0 and repeated.unchanged == 1
    assert artifact.artifact_metadata["category"] == "SecurityNotification"
    assert artifact.artifact_metadata["classification"]["classifier_version"] == "rules-v3"
    assert artifact.artifact_type == "security_notification"
    assert buckets_for(artifact) == ()
    for key in ("summary", "sentiment_label", "custom"):
        assert artifact.artifact_metadata[key] == original[key]


def test_reclassification_reports_unknown_documents() -> None:
    artifact = _artifact(
        artifact_id=1,
        ticker="CSL",
        title="Product Launch",
        raw_text="The company launched a new product for enterprise customers.",
    )

    summary = reclassify_records(
        [artifact],
        ReclassificationOptions(dry_run=False, batch_size=10, limit=10),
    )

    assert summary.changed == 1
    assert summary.unknown == 1
    assert artifact.artifact_metadata["category"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("field", "value"),
    (("batch_size", 0), ("batch_size", 501), ("limit", 0), ("limit", 10_001)),
)
def test_reclassification_options_are_bounded(field: str, value: int) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError):
        ReclassificationOptions(**kwargs)
