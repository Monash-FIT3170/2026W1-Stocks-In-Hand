"""CLI evaluator for the legacy and current deterministic classifiers."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from tools.classification_evaluator import (
    EvaluationPrediction,
    evaluate_predictions,
    load_fixture_text,
    load_manifest,
)


_LEGACY_TO_STABLE = {
    "QuarterlyTradingUpdate": "quarterly_trading_update",
    "HalfYearResults": "half_year_results",
    "DividendAnnouncement": "dividend_announcement",
    "SecurityNotification": "security_notification",
    "CorporateAction": "corporate_action",
    "LeadershipChange": "leadership_change",
    "ExecutiveTranscript": "executive_transcript",
}


def _legacy_predictor(
    fixture: Mapping[str, Any], text: str
) -> EvaluationPrediction:
    from parsing.classifier import classify  # pylint: disable=import-outside-toplevel

    category, _score, _method = classify(str(fixture.get("title") or ""), text)
    stable_category = _LEGACY_TO_STABLE.get(category.__name__) if category else None
    return EvaluationPrediction(
        fixture_id=str(fixture["id"]),
        status="classified" if stable_category else "unknown",
        primary_category=stable_category,
    )


def _current_predictor(
    fixture: Mapping[str, Any], text: str
) -> EvaluationPrediction:
    from parsing.classification import (  # pylint: disable=import-outside-toplevel
        ClassificationInput,
        classify_document,
    )

    result = classify_document(
        ClassificationInput(
            title=str(fixture.get("title") or ""),
            filename=fixture.get("filename"),
            text=text,
            source_type=fixture.get("source_type"),
            source_adapter=fixture.get("source_adapter"),
        )
    )
    return EvaluationPrediction(
        fixture_id=str(fixture["id"]),
        status=result.status,
        primary_category=result.primary_category,
    )


def evaluate_manifest(manifest_path: Path, *, classifier: str) -> dict[str, Any]:
    """Evaluate every manifest entry with the selected classifier."""
    fixtures = load_manifest(manifest_path)
    predictors: dict[
        str, Callable[[Mapping[str, Any], str], EvaluationPrediction]
    ] = {
        "legacy": _legacy_predictor,
        "current": _current_predictor,
    }
    try:
        predictor = predictors[classifier]
    except KeyError as exc:
        raise ValueError(f"Unsupported classifier: {classifier}") from exc

    predictions: list[EvaluationPrediction] = []
    durations_ms: list[float] = []
    for fixture in fixtures:
        text = load_fixture_text(manifest_path, fixture)
        started = time.perf_counter()
        predictions.append(predictor(fixture, text))
        durations_ms.append((time.perf_counter() - started) * 1000)

    report = evaluate_predictions(fixtures, predictions)
    sorted_durations = sorted(durations_ms)
    midpoint = len(sorted_durations) // 2
    report.update(
        {
            "classifier": classifier,
            "median_duration_ms": round(sorted_durations[midpoint], 4),
            "predictions": [
                {
                    "id": prediction.fixture_id,
                    "status": prediction.status,
                    "primary_category": prediction.primary_category,
                }
                for prediction in predictions
            ],
        }
    )
    return report


def _parser() -> argparse.ArgumentParser:
    backend_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Evaluate document classification")
    parser.add_argument("--classifier", choices=("legacy", "current"), required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=backend_dir
        / "tests"
        / "fixtures"
        / "classification"
        / "manifest.json",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    """Run the evaluator and print or persist its JSON report."""
    args = _parser().parse_args()
    report = evaluate_manifest(args.manifest, classifier=args.classifier)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
