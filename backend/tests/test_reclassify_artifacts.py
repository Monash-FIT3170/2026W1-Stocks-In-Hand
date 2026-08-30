from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools.reclassify_artifacts import (
    ReclassificationOptions,
    reclassify_records,
)


def _artifact(
    *,
    artifact_id: int,
    ticker: str,
    title: str,
    raw_text: str,
    metadata: dict | None = None,
):
    return SimpleNamespace(
        id=artifact_id,
        ticker=SimpleNamespace(symbol=ticker),
        title=title,
        raw_text=raw_text,
        source_type="asx_announcement",
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
