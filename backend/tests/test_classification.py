from __future__ import annotations

from pathlib import Path

from parsing.classification import ClassificationInput, classify_document
from parsing.classifier import classify
from parsing.analysis import ParsedDocument, apply_rules
from parsing.classification_metadata import merge_classification_metadata
from tools.evaluate_classification import evaluate_manifest


def test_strong_form_evidence_selects_half_year_results() -> None:
    result = classify_document(
        ClassificationInput(
            title="Appendix 4D and Interim Financial Report",
            filename="appendix_4d.pdf",
            text="Half-year report for the six months ended 31 December 2025.",
        )
    )

    assert result.status == "classified"
    assert result.primary_category == "half_year_results"
    assert result.compatibility_category == "HalfYearResults"
    assert result.score >= 0.65
    assert result.classifier_version == "rules-v2"
    assert result.candidates[0].category == "half_year_results"
    assert any(
        evidence.rule == "appendix_4d"
        and evidence.matched_text.lower() == "appendix 4d"
        for evidence in result.candidates[0].evidence
    )


def test_body_only_classification_requires_multiple_supporting_phrases() -> None:
    weak = classify_document(
        ClassificationInput(
            title="Company update",
            text="The document is an interim financial report.",
        )
    )
    supported = classify_document(
        ClassificationInput(
            title="Company update",
            text=(
                "This half year report is an interim financial report for the "
                "six months ended 31 December and includes condensed financial "
                "statements."
            ),
        )
    )

    assert weak.status == "unknown"
    assert supported.status == "classified"
    assert supported.primary_category == "half_year_results"


def test_short_patterns_match_only_as_whole_tokens() -> None:
    quarterly = classify_document(
        ClassificationInput(
            title="Q1 Trading Update",
            text="Quarterly sales and operating volumes for the quarter.",
        )
    )
    embedded = classify_document(
        ClassificationInput(
            title="Acquisition of Q1Labs",
            text="The company acquired the software business.",
        )
    )

    assert quarterly.status == "classified"
    assert quarterly.primary_category == "quarterly_trading_update"
    assert embedded.primary_category != "quarterly_trading_update"


def test_negative_evidence_prevents_interim_dividend_false_positive() -> None:
    result = classify_document(
        ClassificationInput(
            title="Interim Dividend Announcement",
            text=(
                "The dividend relates to the six months ended 31 December. "
                "The board declared 18 cents per share with a payment date."
            ),
        )
    )

    assert result.status == "classified"
    assert result.primary_category == "dividend_announcement"
    half_year = next(
        candidate
        for candidate in result.candidates
        if candidate.category == "half_year_results"
    )
    assert any(
        evidence.rule == "dividend_conflict" and evidence.weight < 0
        for evidence in half_year.evidence
    )


def test_close_top_two_categories_require_review() -> None:
    result = classify_document(
        ClassificationInput(
            title="Q2 Trading and Guidance Update",
            text=(
                "The update equally covers quarterly sales for the quarter and "
                "revised earnings guidance for the full year."
            ),
        )
    )

    assert result.status == "needs_review"
    assert result.compatibility_category == "UNKNOWN"
    assert {candidate.category for candidate in result.candidates[:2]} == {
        "quarterly_trading_update",
        "guidance_update",
    }
    assert result.candidates[0].score - result.candidates[1].score < 0.15


def test_unknown_empty_large_and_malformed_inputs_are_bounded_and_safe() -> None:
    empty = classify_document(ClassificationInput(title="", text=""))
    beyond_body_limit = classify_document(
        ClassificationInput(
            title="General update",
            text="x" * 50_001 + " Appendix 4D interim financial report",
        )
    )
    malformed = classify_document(  # type: ignore[arg-type]
        ClassificationInput(title=None, text={"unexpected": "value"})
    )

    assert empty.status == "unknown"
    assert empty.primary_category is None
    assert empty.compatibility_category == "UNKNOWN"
    assert beyond_body_limit.status == "unknown"
    assert malformed.status == "unknown"


def test_candidate_and_evidence_order_is_deterministic() -> None:
    document = ClassificationInput(
        title="Q2 Trading and Guidance Update",
        filename="q2_guidance_update.pdf",
        text="Quarterly sales for the quarter and revised earnings guidance.",
    )

    first = classify_document(document)
    second = classify_document(document)

    assert first == second
    assert [candidate.category for candidate in first.candidates] == sorted(
        (candidate.category for candidate in first.candidates),
        key=lambda category: (
            -next(
                candidate.score
                for candidate in first.candidates
                if candidate.category == category
            ),
            category,
        ),
    )


def test_unsupported_source_metadata_fails_closed() -> None:
    result = classify_document(
        ClassificationInput(
            title="2026 Annual Report",
            text="Annual report with audited financial statements.",
            source_type="reddit_post",
            source_adapter="reddit",
        )
    )

    assert result.status == "unknown"
    assert result.primary_category is None
    assert result.compatibility_category == "UNKNOWN"

def test_labelled_fixture_quality_gates_pass() -> None:
    manifest = Path(__file__).parent / "fixtures" / "classification" / "manifest.json"

    report = evaluate_manifest(manifest, classifier="current")

    assert report["macro_f1"] >= 0.85
    assert report["unknown_false_positive_rate"] <= 0.10
    for metrics in report["per_category"].values():
        if metrics["fixture_count"] >= 5:
            assert metrics["precision"] >= 0.75
            assert metrics["recall"] >= 0.75


def test_legacy_wrapper_delegates_and_fails_closed_for_review() -> None:
    category, score, method = classify(
        "Appendix 4D and Interim Financial Report",
        "Half-year report for the six months ended 31 December 2025.",
    )
    ambiguous_category, ambiguous_score, ambiguous_method = classify(
        "Q2 Trading and Guidance Update",
        "Quarterly sales for the quarter and revised earnings guidance.",
    )

    assert category is not None and category.__name__ == "HalfYearResults"
    assert score >= 0.65
    assert method == "rules-v2"
    assert ambiguous_category is None
    assert ambiguous_score >= 0.65
    assert ambiguous_method == "rules-v2"


def test_apply_rules_extracts_only_for_classified_documents() -> None:
    parsed = ParsedDocument(
        raw_text=(
            "The board declared an interim dividend of 18 cents per share. "
            "The dividend payment date is Wednesday, 1 July 2026."
        ),
        page_count=1,
        category="UNKNOWN",
        category_confidence=0.0,
        extracted_data={},
    )
    classified = apply_rules(
        parsed,
        title="Interim Dividend Announcement",
        filename="interim_dividend.pdf",
        source_type="asx_announcement",
        source_adapter="anz",
    )
    ambiguous = apply_rules(
        parsed,
        title="Q2 Trading and Guidance Update",
        filename="q2_guidance_update.pdf",
    )

    assert classified.category == "DividendAnnouncement"
    assert classified.extracted_data["amount_per_share"] == "18 cents"
    assert classified.classification is not None
    assert classified.classification.status == "classified"
    assert ambiguous.category == "UNKNOWN"
    assert ambiguous.extracted_data == {}
    assert ambiguous.classification is not None
    assert ambiguous.classification.status == "needs_review"


def test_metadata_merge_preserves_unrelated_and_prior_extracted_data() -> None:
    existing = {
        "source_url": "https://example.test/report",
        "category": "HalfYearResults",
        "extracted_data": {"revenue": "$10m"},
        "custom": {"keep": True},
    }
    ambiguous = classify_document(
        ClassificationInput(
            title="Q2 Trading and Guidance Update",
            text="Quarterly sales for the quarter and revised earnings guidance.",
        )
    )

    updated = merge_classification_metadata(existing, ambiguous)

    assert updated["source_url"] == existing["source_url"]
    assert updated["custom"] == {"keep": True}
    assert updated["extracted_data"] == {"revenue": "$10m"}
    assert updated["extracted_data_stale"] is True
    assert updated["category"] == "UNKNOWN"
    assert updated["category_confidence"] == ambiguous.score
    assert updated["classification_method"] == "rules-v2"
    assert updated["classification"]["status"] == "needs_review"
