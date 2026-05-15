from __future__ import annotations

from .base import ReportCategory


class QuarterlyTradingUpdate(ReportCategory):
    """Quarterly operational/trading update (e.g. ANZ 1Q FY2026 Trading Update)."""

    name = "QuarterlyTradingUpdate"

    _TITLE_KEYWORDS = ["quarterly", "trading update", "quarter update"]
    _TITLE_PATTERNS = ["1q", "2q", "3q", "4q", "q1", "q2", "q3", "q4"]
    _TEXT_KEYWORDS = ["quarterly", "quarter", "trading update"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        return {}
