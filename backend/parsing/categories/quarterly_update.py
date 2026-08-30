from __future__ import annotations

from .base import ReportCategory


class QuarterlyTradingUpdate(ReportCategory):
    """Quarterly operational/trading update (e.g. ANZ 1Q FY2026 Trading Update)."""

    name = "QuarterlyTradingUpdate"

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        return {}
