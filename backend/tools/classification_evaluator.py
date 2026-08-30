"""Metrics for the labelled document-classification fixture set."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class EvaluationPrediction:
    """Minimal classifier output required by the evaluator."""
    fixture_id: str
    status: str
    primary_category: str | None


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load and validate the top-level fixture manifest shape."""
    data = json.loads(path.read_text(encoding="utf-8"))
    fixtures = data.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("Classification manifest must contain a fixtures list")
    return fixtures


def load_fixture_text(manifest_path: Path, fixture: Mapping[str, Any]) -> str:
    """Read one fixture excerpt relative to its manifest."""
    relative_path = fixture.get("text_path")
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError(f"Fixture {fixture.get('id')!r} has no text_path")
    return (manifest_path.parent / relative_path).read_text(encoding="utf-8")


def _prediction_label(
    fixture: Mapping[str, Any], prediction: EvaluationPrediction
) -> str:
    expected = str(fixture["expected_category"])
    if prediction.status != "classified" or not prediction.primary_category:
        return "unknown"
    alternatives = fixture.get("acceptable_alternatives") or []
    if expected != "unknown" and prediction.primary_category in alternatives:
        return expected
    return prediction.primary_category


def _rounded_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


# pylint: disable-next=too-many-locals
def evaluate_predictions(
    fixtures: Sequence[Mapping[str, Any]],
    predictions: Iterable[EvaluationPrediction],
) -> dict[str, Any]:
    """Calculate counts, confusion, precision, recall and macro F1."""
    prediction_by_id = {prediction.fixture_id: prediction for prediction in predictions}
    if len(prediction_by_id) != len(fixtures):
        raise ValueError("Every fixture must have exactly one prediction")

    expected_counts: Counter[str] = Counter()
    predicted_counts: Counter[str] = Counter()
    confusion: defaultdict[str, Counter[str]] = defaultdict(Counter)
    ambiguous_count = 0

    for fixture in fixtures:
        fixture_id = str(fixture["id"])
        try:
            prediction = prediction_by_id[fixture_id]
        except KeyError as exc:
            raise ValueError(f"Missing prediction for fixture {fixture_id}") from exc
        expected = str(fixture["expected_category"])
        predicted = _prediction_label(fixture, prediction)
        expected_counts[expected] += 1
        predicted_counts[predicted] += 1
        confusion[expected][predicted] += 1
        if prediction.status == "needs_review":
            ambiguous_count += 1

    categories = sorted(category for category in expected_counts if category != "unknown")
    per_category: dict[str, dict[str, float | int]] = {}
    f1_scores: list[float] = []
    for category in categories:
        true_positive = confusion[category][category]
        predicted_total = predicted_counts[category]
        expected_total = expected_counts[category]
        precision = _rounded_ratio(true_positive, predicted_total)
        recall = _rounded_ratio(true_positive, expected_total)
        f1 = (
            round(2 * precision * recall / (precision + recall), 4)
            if precision + recall
            else 0.0
        )
        per_category[category] = {
            "fixture_count": expected_total,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        f1_scores.append(f1)

    unknown_total = expected_counts["unknown"]
    unknown_false_positives = unknown_total - confusion["unknown"]["unknown"]
    return {
        "fixture_count": len(fixtures),
        "category_counts": {
            "expected": dict(sorted(expected_counts.items())),
            "predicted": dict(sorted(predicted_counts.items())),
        },
        "confusion_matrix": {
            expected: dict(sorted(predicted.items()))
            for expected, predicted in sorted(confusion.items())
        },
        "per_category": per_category,
        "macro_f1": round(sum(f1_scores) / len(f1_scores), 4)
        if f1_scores
        else 0.0,
        "unknown_false_positive_rate": _rounded_ratio(
            unknown_false_positives, unknown_total
        ),
        "ambiguous_count": ambiguous_count,
    }
