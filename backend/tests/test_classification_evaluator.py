from __future__ import annotations

from pathlib import Path

from tools.classification_evaluator import EvaluationPrediction, evaluate_predictions
from tools.evaluate_classification import evaluate_manifest


def test_evaluator_reports_quality_and_ambiguity_metrics() -> None:
    expected = [
        {"id": "a", "expected_category": "annual_report"},
        {"id": "b", "expected_category": "annual_report"},
        {"id": "c", "expected_category": "dividend_announcement"},
        {"id": "d", "expected_category": "unknown"},
    ]
    predictions = [
        EvaluationPrediction("a", "classified", "annual_report"),
        EvaluationPrediction("b", "classified", "dividend_announcement"),
        EvaluationPrediction("c", "needs_review", "dividend_announcement"),
        EvaluationPrediction("d", "classified", "annual_report"),
    ]

    report = evaluate_predictions(expected, predictions)

    assert report["fixture_count"] == 4
    assert report["ambiguous_count"] == 1
    assert report["unknown_false_positive_rate"] == 1.0
    assert report["category_counts"]["expected"] == {
        "annual_report": 2,
        "dividend_announcement": 1,
        "unknown": 1,
    }
    assert report["confusion_matrix"]["annual_report"] == {
        "annual_report": 1,
        "dividend_announcement": 1,
    }
    assert report["per_category"]["annual_report"] == {
        "fixture_count": 2,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
    }
    assert report["macro_f1"] == 0.25


def test_labelled_manifest_has_required_fixture_coverage() -> None:
    manifest = Path(__file__).parent / "fixtures" / "classification" / "manifest.json"

    report = evaluate_manifest(manifest, classifier="legacy-baseline")

    assert report["fixture_count"] == 85
    assert report["category_counts"]["expected"]["unknown"] == 20
    supported_counts = {
        category: count
        for category, count in report["category_counts"]["expected"].items()
        if category != "unknown"
    }
    assert len(supported_counts) == 13
    assert set(supported_counts.values()) == {5}


def test_frozen_legacy_baseline_reproduces_the_recorded_report() -> None:
    """docs/advanced-content-classification-baseline-report.md, recorded at dabaaf0."""
    manifest = Path(__file__).parent / "fixtures" / "classification" / "manifest.json"

    report = evaluate_manifest(manifest, classifier="legacy-baseline")

    assert round(report["macro_f1"], 4) == 0.4765
    assert report["unknown_false_positive_rate"] == 0.15
    assert report["ambiguous_count"] == 0
    recorded_f1 = {
        "corporate_action": 0.9091,
        "dividend_announcement": 0.8,
        "executive_transcript": 0.8889,
        "half_year_results": 0.9091,
        "leadership_change": 0.8889,
        "quarterly_trading_update": 0.9091,
        "security_notification": 0.8889,
    }
    assert {
        category: round(metrics["f1"], 4)
        for category, metrics in report["per_category"].items()
        if metrics["f1"]
    } == recorded_f1


def test_acceptable_alternative_does_not_hide_unknown_false_positive() -> None:
    expected = [
        {
            "id": "ambiguous",
            "expected_category": "unknown",
            "acceptable_alternatives": ["annual_report", "governance_meeting"],
        }
    ]

    report = evaluate_predictions(
        expected,
        [EvaluationPrediction("ambiguous", "classified", "annual_report")],
    )

    assert report["unknown_false_positive_rate"] == 1.0
