"""Evaluate content topic tagging against the labelled fixture set.

By default the rules alone tag each fixture, which needs only the standard
library, so CI can gate on it. ``--llm`` tags them through
``app.services.content_topics.decide_topics`` with the configured LLM
instead, which costs one call per fixture and is for a manual comparison.

The report gives each topic's precision, recall and F1, their micro
average, and every fixture whose topics differ from its labels.

    cd backend
    python -m tools.evaluate_content_topics
    python -m tools.evaluate_content_topics --min-f1 0.8
    python -m tools.evaluate_content_topics --llm --output /tmp/topics-llm.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from parsing.content_topics import TOPIC_IDENTIFIERS, TopicInput, detect_topics

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "content_topics" / "manifest.json"
)
# The confidence the analysis worker records topics at by default.
DEFAULT_MIN_CONFIDENCE = 0.5

Predictor = Callable[[TopicInput], set[str]]


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """The manifest's fixtures, each checked to name only known topics."""
    data = json.loads(path.read_text(encoding="utf-8"))
    fixtures = data["fixtures"]
    for fixture in fixtures:
        unknown = set(fixture["expected_topics"]) - set(TOPIC_IDENTIFIERS)
        if unknown:
            raise ValueError(f"{fixture['id']} expects unknown topics: {sorted(unknown)}")
    return fixtures


def fixture_input(fixture: Mapping[str, Any]) -> TopicInput:
    return TopicInput(
        title=str(fixture.get("title") or ""),
        text=str(fixture.get("text") or ""),
        category=fixture.get("category"),
        source_type=fixture.get("source_type"),
    )


def rules_predictor(min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> Predictor:
    """The topics the rules would record for a fixture."""

    def predict(source: TopicInput) -> set[str]:
        return {match.topic for match in detect_topics(source) if match.score >= min_confidence}

    return predict


def llm_predictor(min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> Predictor:
    """The topics the configured LLM, with rule hints, would record for a fixture."""
    # Imported on use: the rules evaluation needs nothing outside the standard library.
    from app.services.content_topics import (  # pylint: disable=import-outside-toplevel
        decide_topics,
    )

    def predict(source: TopicInput) -> set[str]:
        decision = decide_topics(source, use_llm=True, min_confidence=min_confidence)
        if decision.method != "llm":
            raise RuntimeError(
                f"The LLM did not tag a fixture ({decision.llm_error or 'no LLM switched on'})"
            )
        return {record.topic for record in decision.topics}

    return predict


def evaluate(
    fixtures: Sequence[Mapping[str, Any]],
    predict: Predictor,
) -> dict[str, Any]:
    """Per-topic and micro-averaged precision, recall and F1, and every mismatch."""
    counts = {topic: {"tp": 0, "fp": 0, "fn": 0} for topic in TOPIC_IDENTIFIERS}
    mismatches = []
    for fixture in fixtures:
        expected = set(fixture["expected_topics"])
        predicted = predict(fixture_input(fixture))
        for topic in TOPIC_IDENTIFIERS:
            if topic in predicted and topic in expected:
                counts[topic]["tp"] += 1
            elif topic in predicted:
                counts[topic]["fp"] += 1
            elif topic in expected:
                counts[topic]["fn"] += 1
        if predicted != expected:
            mismatches.append(
                {
                    "id": fixture["id"],
                    "expected": sorted(expected),
                    "predicted": sorted(predicted),
                }
            )
    topics = {topic: _scores(**values) for topic, values in counts.items()}
    total = {
        key: sum(values[key] for values in counts.values()) for key in ("tp", "fp", "fn")
    }
    return {
        "fixtures": len(fixtures),
        "exact_matches": len(fixtures) - len(mismatches),
        "topics": topics,
        "micro": _scores(**total),
        "mismatches": mismatches,
    }


def _scores(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate content topic tagging")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument(
        "--llm",
        action="store_true",
        help="tag through the configured LLM, one paid call per fixture",
    )
    parser.add_argument(
        "--min-f1",
        type=float,
        help="exit with status 1 when the micro-averaged F1 is below this",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    """Run the evaluation and print or save its JSON report."""
    args = _parser().parse_args()
    fixtures = load_manifest(args.manifest)
    predict = (llm_predictor if args.llm else rules_predictor)(args.min_confidence)
    report = {"tagger": "llm" if args.llm else "rules", **evaluate(fixtures, predict)}
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.min_f1 is not None and report["micro"]["f1"] < args.min_f1:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
