"""
Classifies ASX announcement PDFs into report categories and extracts structured data.

We use rule based confidence scoring on the document title to determine what kind of report it is.
If we do not have a high confidence score, we use an LLM to help classify.
To test the classifier, go to pipeline.py and read comment at top of file. 

Each category (e.g. QuarterlyTradingUpdate, HalfYearResults) is a ReportCategory subclass
that owns its confidence scoring rules, LLM extraction prompt, and output schema.
To add a new category: subclass ReportCategory, implement get_confidence and get_llm_prompt,
then append the class to CATEGORIES.

"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from groq import Groq

_LLM_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
_RULE_HIGH_THRESHOLD = 6
_RULE_MED_THRESHOLD = 3

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


class ReportCategory(ABC):
    """
    Base class for all report categories. Each subclass encapsulates:
    - Rule-based confidence scoring (get_confidence)
    - The LLM extraction prompt for this report type (get_llm_prompt)
    - Structured data extraction via the LLM (get_output)
    """

    name: str  # Override in each subclass

    @classmethod
    @abstractmethod
    def get_confidence(cls, title: str, text: str = "") -> float:
        """Returns rule-based confidence (0.0–1.0) that title/text matches this category."""
        ...

    @classmethod
    @abstractmethod
    def get_llm_prompt(cls, title: str, text: str) -> str:
        """Returns the extraction prompt for this report type."""
        ...

    @classmethod
    def get_output(cls, title: str, text: str, client: Groq) -> dict:
        """Calls the LLM with this category's extraction prompt and returns a Python dict."""
        prompt = cls.get_llm_prompt(title, text)
        response = client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        try:
            result = json.loads(raw)
            return result if isinstance(result, dict) else {"raw_response": raw}
        except json.JSONDecodeError:
            return {"raw_response": raw}


class QuarterlyTradingUpdate(ReportCategory):
    name = "QUARTERLY_TRADING_UPDATE"

    _TITLE_KEYWORDS = ["quarterly", "trading update", "quarter update"]
    _TITLE_PATTERNS = ["1q", "2q", "3q", "4q", "q1", "q2", "q3", "q4"]
    _TEXT_KEYWORDS = ["quarterly", "quarter", "trading update"]

    @classmethod
    def get_confidence(cls, title: str, text: str = "") -> float:
        score = 0
        title_lower = title.lower()
        for kw in cls._TITLE_KEYWORDS:
            if kw in title_lower:
                score += 3
        for pat in cls._TITLE_PATTERNS:
            if re.search(r"(?<![a-z0-9])" + re.escape(pat) + r"(?![a-z0-9])", title_lower):
                score += 3
        text_lower = text[:3000].lower()
        for kw in cls._TEXT_KEYWORDS:
            if kw in text_lower:
                score += 1
        if score >= _RULE_HIGH_THRESHOLD:
            return 1.0
        if score >= _RULE_MED_THRESHOLD:
            return 0.7
        return score / _RULE_HIGH_THRESHOLD

    @classmethod
    def get_llm_prompt(cls, title: str, text: str) -> str:
        return f"""\
        You are a financial analyst extracting structured data from an ASX quarterly trading update.

        Title: {title}

        Report text:
        {text[:12000]}

        Return JSON only, no explanation:
        {{
        "period": "e.g. 1Q FY2026",
        "key_metrics": {{"metric_name": "value as string"}},
        "outlook": "1-2 sentence summary of forward-looking guidance",
        "raw_summary": "2-3 sentence plain-English summary"
        }}"""


class HalfYearResults(ReportCategory):
    name = "HALF_YEAR_RESULTS"

    _TITLE_KEYWORDS = ["half year", "half-year", "interim results", "interim"]
    _TITLE_PATTERNS = ["1h", "2h", "h1", "h2", "6 months", "six months"]
    _TEXT_KEYWORDS = ["half year", "half-year", "interim", "six months"]

    @classmethod
    def get_confidence(cls, title: str, text: str = "") -> float:
        score = 0
        title_lower = title.lower()
        for kw in cls._TITLE_KEYWORDS:
            if kw in title_lower:
                score += 3
        for pat in cls._TITLE_PATTERNS:
            if re.search(r"(?<![a-z0-9])" + re.escape(pat) + r"(?![a-z0-9])", title_lower):
                score += 3
        text_lower = text[:3000].lower()
        for kw in cls._TEXT_KEYWORDS:
            if kw in text_lower:
                score += 1
        if score >= _RULE_HIGH_THRESHOLD:
            return 1.0
        if score >= _RULE_MED_THRESHOLD:
            return 0.7
        return score / _RULE_HIGH_THRESHOLD

    @classmethod
    def get_llm_prompt(cls, title: str, text: str) -> str:
        return f"""\
        You are a financial analyst extracting structured data from an ASX half-year (interim) results announcement.

        Title: {title}

        Report text:
        {text[:12000]}

        Return JSON only, no explanation:
        {{
        "period": "e.g. 1H FY2026",
        "revenue": "total revenue with currency e.g. $10.2B",
        "npat": "net profit after tax with currency",
        "eps": "earnings per share with units e.g. 145.2 cents",
        "dividend": "dividend per share, or null if not mentioned",
        "key_highlights": ["bullet 1", "bullet 2", "bullet 3"]
        }}"""


# Register new categories here to extend the pipeline
CATEGORIES: list[type[ReportCategory]] = [
    QuarterlyTradingUpdate,
    HalfYearResults,
]


def classify(
    title: str, text: str, client: Groq
) -> tuple[type[ReportCategory] | None, float, str]:
    """
    Returns (category_class_or_None, confidence, method).
    method is "rules" or "llm". category_class is None when UNKNOWN.
    """
    scores = {cat: cat.get_confidence(title, text) for cat in CATEGORIES}
    best_cat = max(scores, key=lambda c: scores[c])
    best_score = scores[best_cat]

    if best_score >= 0.7:
        return best_cat, best_score, "rules"

    return _classify_by_llm(title, text, client)


def _classify_by_llm(
    title: str, text: str, client: Groq
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
