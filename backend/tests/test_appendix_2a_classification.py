"""Appendix 2A quotation notices are administrative security notifications."""

from pathlib import Path

import pytest

from parsing.classification import ClassificationInput, classify_document
from tools.evaluate_classification import evaluate_manifest


@pytest.mark.parametrize(
    "document",
    [
        ClassificationInput(title="Application for quotation of securities - ANZ", text=""),
        ClassificationInput(title="Application for quotation of +securities", text=""),
        ClassificationInput(title="Appendix 2A", text=""),
        ClassificationInput(title="appendix2a", text=""),
        ClassificationInput(title="APPENDIX-2A", text=""),
        ClassificationInput(title="Company update", filename="appendix_2a.pdf", text=""),
        ClassificationInput(
            title="Company update", text="Appendix 2A\nTotal number of +securities on issue."
        ),
    ],
    ids=["title", "asx-markup", "form-title", "compact-form", "hyphenated-form", "filename", "body"],
)
def test_quotation_notice_is_a_security_notification(document):
    result = classify_document(document)

    assert result.status == "classified"
    assert result.primary_category == "security_notification"
    assert result.compatibility_category == "SecurityNotification"
    assert result.classifier_version == "rules-v3"
    assert result.candidates[0].evidence


@pytest.mark.parametrize("form", ["Appendix 2AB", "Appendix 2A1", "Appendix 2A.1", "PreAppendix 2A"])
def test_form_recognition_does_not_match_a_partial_identifier(form):
    result = classify_document(ClassificationInput(title=form, text=""))

    assert result.status == "unknown"
    assert result.primary_category is None


def test_an_incidental_body_reference_alone_still_requires_review():
    result = classify_document(
        ClassificationInput(title="Company update", text="Refer to Appendix 2A for details.")
    )

    assert result.status == "needs_review"
    assert result.compatibility_category == "UNKNOWN"


def test_news_about_an_appendix_does_not_become_an_official_notice():
    result = classify_document(
        ClassificationInput(title="Application for quotation of securities", text="Appendix 2A", source_type="news")
    )

    assert result.status == "unknown"


def test_capital_raising_context_is_not_hidden_by_an_appendix_reference():
    result = classify_document(
        ClassificationInput(
            title="Placement and Entitlement Offer",
            text="The entitlement offer will be followed by an Appendix 2A.",
        )
    )

    assert result.status == "classified"
    assert result.primary_category == "capital_management"


def test_appendix_2a_regression_corpus_has_no_misclassifications():
    manifest = Path(__file__).parent / "fixtures" / "classification" / "appendix_2a_manifest.json"
    report = evaluate_manifest(manifest, classifier="current")

    assert report["fixture_count"] == 9
    assert report["macro_f1"] == 1.0
    assert report["unknown_false_positive_rate"] == 0.0
    assert report["ambiguous_count"] == 1
