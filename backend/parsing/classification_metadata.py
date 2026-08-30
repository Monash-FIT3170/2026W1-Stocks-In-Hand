"""JSON persistence adapter for immutable classification results."""

from __future__ import annotations

from typing import Any

from parsing.classification import ClassificationResult


def classification_metadata(result: ClassificationResult) -> dict[str, Any]:
    """Convert an immutable result to its persisted JSON representation."""
    return {
        "status": result.status,
        "primary_category": result.primary_category,
        "compatibility_category": result.compatibility_category,
        "score": result.score,
        "classifier_version": result.classifier_version,
        "candidates": [
            {
                "category": candidate.category,
                "score": candidate.score,
                "evidence": [
                    {
                        "field": evidence.field,
                        "rule": evidence.rule,
                        "matched_text": evidence.matched_text,
                        "weight": evidence.weight,
                    }
                    for evidence in candidate.evidence
                ],
            }
            for candidate in result.candidates
        ],
    }


def merge_classification_metadata(
    existing: dict[str, Any] | None,
    result: ClassificationResult,
) -> dict[str, Any]:
    """Merge structured and legacy fields without discarding other analysis."""
    metadata = dict(existing) if isinstance(existing, dict) else {}
    previous_category = metadata.get("category")
    metadata.update(
        {
            "classification": classification_metadata(result),
            "category": result.compatibility_category,
            "category_confidence": result.score,
            "classification_method": result.classifier_version,
        }
    )
    if (
        previous_category != result.compatibility_category
        and isinstance(metadata.get("extracted_data"), dict)
        and metadata["extracted_data"]
    ):
        metadata["extracted_data_stale"] = True
    return metadata
