"""
Classifies ASX announcement PDFs into report categories using rule-based scoring.

Each category declares keyword lists; get_confidence() scores the title and
text against those lists. The highest-scoring category wins if it meets the
confidence threshold.

To add a new category: subclass ReportCategory in categories/, declare keyword
lists and implement extract(), then append to CATEGORIES in categories/__init__.py.
"""
from __future__ import annotations

from categories import CATEGORIES, ReportCategory


def classify(
    title: str,
    text: str,
) -> tuple[type[ReportCategory] | None, float, str]:
    """
    Returns (category_class | None, confidence, method).

    method is always "rules". category_class is None when no category scores > 0.
    """
    scores = {cat: cat.get_confidence(title, text) for cat in CATEGORIES}
    best_cat = max(scores, key=lambda c: scores[c])
    best_score = scores[best_cat]

    if best_score >= 0.7:
        return best_cat, best_score, "rules"

    return (best_cat, best_score, "rules") if best_score > 0 else (None, 0.0, "rules")
