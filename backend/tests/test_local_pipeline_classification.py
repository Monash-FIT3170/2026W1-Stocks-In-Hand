from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from parsing.classification import ClassificationInput, classify_document
from scrapers.base import Announcement


def test_local_pipeline_uses_same_structured_classification_contract(
    monkeypatch,
) -> None:
    from parsing import pipeline

    text = "Appendix 4D. Half year report for the six months ended 31 December."
    announcement = Announcement(
        ticker="CSL",
        title="Appendix 4D and Interim Financial Report",
        date=datetime(2026, 2, 1, tzinfo=timezone.utc),
        pdf_url="https://example.test/report.pdf",
        source_url="https://example.test/announcement",
        local_path=Path("appendix_4d.pdf"),
    )
    stored: dict[str, object] = {}
    monkeypatch.setattr(pipeline, "extract_text", lambda _path: text)

    def fake_store(*_args, **kwargs) -> None:
        stored.update(kwargs)

    monkeypatch.setattr(pipeline, "store", fake_store)

    report = pipeline.process_announcement(announcement)
    direct = classify_document(
        ClassificationInput(
            title=announcement.title,
            text=text,
            filename="appendix_4d.pdf",
            source_type="asx_announcement",
            source_adapter="csl",
        )
    )

    assert report.classification == direct
    assert report.category == "HalfYearResults"
    assert report.method == "rules-v2"
    assert stored["classification"] == direct
    assert stored["raw_text"] == text
