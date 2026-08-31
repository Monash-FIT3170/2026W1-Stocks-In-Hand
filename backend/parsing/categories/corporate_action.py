from __future__ import annotations

from .base import ReportCategory


class CorporateAction(ReportCategory):
    """M&A, acquisitions, divestments, joint venture changes."""

    name = "CorporateAction"

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        return {}
