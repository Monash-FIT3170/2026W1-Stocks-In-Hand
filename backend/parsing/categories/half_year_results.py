from __future__ import annotations

from .base import ReportCategory


class HalfYearResults(ReportCategory):
    """Half-year (interim) financial results announcement."""

    name = "HalfYearResults"

    _TITLE_KEYWORDS = [
        "half year", "half-year", "interim results", "interim",
        "appendix 4d", "half year result",
    ]
    _TITLE_PATTERNS = ["1h", "2h", "h1", "h2"]
    _TEXT_KEYWORDS = ["half year", "half-year", "interim", "six months"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        return {}
