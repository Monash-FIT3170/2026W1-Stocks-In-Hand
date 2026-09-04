from __future__ import annotations

from .base import ReportCategory


class HalfYearResults(ReportCategory):
    """Half-year (interim) financial results announcement."""

    name = "HalfYearResults"

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        return {}
