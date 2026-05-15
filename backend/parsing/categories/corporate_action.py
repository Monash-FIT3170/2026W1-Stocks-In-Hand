from __future__ import annotations

from .base import ReportCategory


class CorporateAction(ReportCategory):
    """M&A, acquisitions, divestments, joint venture changes."""

    name = "CorporateAction"

    _TITLE_KEYWORDS = [
        "acquire", "acquisition", "merger", "joint venture",
        "divestment", "divest",
    ]
    _TEXT_KEYWORDS = ["acquire", "merger", "acquisition", "strategic", "transaction"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        return {}
