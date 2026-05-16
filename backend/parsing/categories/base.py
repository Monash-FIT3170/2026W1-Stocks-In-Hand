from __future__ import annotations

import re
from abc import ABC, abstractmethod

_HIGH = 6
_MED = 3


class ReportCategory(ABC):
    """
    Base class for all ASX report categories.

    Subclasses declare keyword/pattern lists and implement extract().
    get_confidence() is provided by the base and requires no override unless
    the category needs non-standard scoring logic.

    To add a new category:
    1. Subclass ReportCategory, set name and keyword lists, implement extract().
    2. Append the class to CATEGORIES in categories/__init__.py.
    """

    name: str

    # Subclasses declare these; base get_confidence() uses them automatically.
    _TITLE_KEYWORDS: list[str] = []
    _TITLE_PATTERNS: list[str] = []  # matched as whole tokens (e.g. "1h", "q1")
    _TEXT_KEYWORDS: list[str] = []

    @classmethod
    def get_confidence(cls, title: str, text: str = "") -> float:
        """
        Rule-based confidence (0.0–1.0) that this report matches the category.
        Title keyword/pattern hit → +3 pts each. Text keyword hit → +1 pt each.
        ≥6 pts → 1.0, ≥3 pts → 0.7, else proportional in [0.0, 0.49].
        """
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

        if score >= _HIGH:
            return 1.0
        if score >= _MED:
            return 0.7
        return score / _HIGH

    @classmethod
    @abstractmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        """
        Extract structured data from the report text.

        Returns a plain Python dict. client is a Groq instance or None.
        Categories that require LLM should raise ValueError if client is None.
        Categories that don't need LLM should ignore client entirely.
        """
        ...
