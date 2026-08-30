"""Compatibility wrapper for the versioned classification module."""

from __future__ import annotations

try:
    from .categories import CATEGORIES, ReportCategory
    from .classification import ClassificationInput, classify_document
except ImportError:  # Support the existing direct CLI execution.
    from categories import CATEGORIES, ReportCategory
    from classification import ClassificationInput, classify_document


_CATEGORY_BY_COMPATIBILITY = {category.__name__: category for category in CATEGORIES}


def classify(
    title: str,
    text: str,
) -> tuple[type[ReportCategory] | None, float, str]:
    """Return the legacy tuple while failing closed for non-classified results."""
    result = classify_document(ClassificationInput(title=title, text=text))
    category = (
        _CATEGORY_BY_COMPATIBILITY.get(result.compatibility_category)
        if result.status == "classified"
        else None
    )
    return category, result.score, result.classifier_version
