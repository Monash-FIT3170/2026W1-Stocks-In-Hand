"""
Classifies ASX announcement PDFs into report categories.

Uses a hybrid approach:
- Rule-based scoring via each category's get_confidence() is tried first.
- If no category scores ≥0.7 and a Groq client is provided, falls back to LLM.
- If no client is provided, returns the best rule-based match (pure offline mode).

To add a new category: subclass ReportCategory in categories/, implement
get_confidence (or declare keyword lists) and extract(), then append to
CATEGORIES in categories/__init__.py.
"""
from __future__ import annotations

import json

from categories import CATEGORIES, ReportCategory

_LLM_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_CLASSIFICATION_PROMPT = """\
Classify this ASX announcement into one of these categories:
{category_list}
- UNKNOWN: anything else

Title: {title}

Excerpt:
{excerpt}

Respond with JSON only:
{{"category": "<CATEGORY_NAME>", "confidence": <0.0-1.0>}}
"""


def classify(
    title: str,
    text: str,
    client=None,
) -> tuple[type[ReportCategory] | None, float, str]:
    """
    Returns (category_class | None, confidence, method).

    method is "rules" or "llm". category_class is None for UNKNOWN reports.
    If client (Groq) is None, operates in pure rule-based mode with no LLM fallback.
    """
    scores = {cat: cat.get_confidence(title, text) for cat in CATEGORIES}
    best_cat = max(scores, key=lambda c: scores[c])
    best_score = scores[best_cat]

    if best_score >= 0.7:
        return best_cat, best_score, "rules"

    if client is None:
        return (best_cat, best_score, "rules") if best_score > 0 else (None, 0.0, "rules")

    return _classify_by_llm(title, text, client)


def _classify_by_llm(
    title: str,
    text: str,
    client,
) -> tuple[type[ReportCategory] | None, float, str]:
    names = "\n".join(f"- {cat.name}" for cat in CATEGORIES)
    prompt = _CLASSIFICATION_PROMPT.format(
        category_list=names, title=title, excerpt=text[:2000]
    )
    response = client.chat.completions.create(
        model=_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
        name = parsed.get("category", "UNKNOWN")
        confidence = float(parsed.get("confidence", 0.5))
        match = next((cat for cat in CATEGORIES if cat.name == name), None)
        return match, confidence, "llm"
    except (json.JSONDecodeError, ValueError):
        return None, 0.0, "llm"
