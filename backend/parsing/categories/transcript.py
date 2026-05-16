from __future__ import annotations

from .base import ReportCategory


class ExecutiveTranscript(ReportCategory):
    """
    Transcript or interview with company executives (e.g. Bluenotes CEO/CFO interviews).
    No structured extraction — qualitative content only.
    """

    name = "ExecutiveTranscript"

    _TITLE_KEYWORDS = ["transcript", "interview", "bluenotes"]
    _TEXT_KEYWORDS = ["transcript", "interview"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        return {}
