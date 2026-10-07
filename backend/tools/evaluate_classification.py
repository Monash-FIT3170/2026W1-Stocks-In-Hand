"""CLI evaluator for the deterministic classifier and the frozen legacy baseline."""

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

LEGACY_BASELINE = "legacy_baseline.json"


def _legacy_baseline_predictor(
    manifest_path: Path,
) -> Callable[[Mapping[str, Any], str], EvaluationPrediction]:
    """Replay the deleted keyword classifier's recorded predictions."""
    baseline = json.loads(
        (manifest_path.parent / LEGACY_BASELINE).read_text(encoding="utf-8")
    )
    recorded = {prediction["id"]: prediction for prediction in baseline["predictions"]}

    def predict(fixture: Mapping[str, Any], _text: str) -> EvaluationPrediction:
        prediction = recorded[str(fixture["id"])]
        return EvaluationPrediction(
            fixture_id=prediction["id"],
            status=prediction["status"],
            primary_category=prediction["primary_category"],
        )

    return predict


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
    """Evaluate every manifest entry with the current classifier or the legacy baseline.

    The legacy keyword classifier is deleted. ``legacy-baseline`` replays the
    predictions it made for these fixtures, recorded in ``legacy_baseline.json``.
    """
    fixtures = load_manifest(manifest_path)
    if classifier == "current":
        predictor = _current_predictor
    elif classifier == "legacy-baseline":
        predictor = _legacy_baseline_predictor(manifest_path)
    else:
        raise ValueError(f"Unsupported classifier: {classifier}")

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
    parser.add_argument(
        "--classifier",
        choices=("current", "legacy-baseline"),
        default="current",
    )
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
