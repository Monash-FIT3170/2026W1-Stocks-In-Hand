from __future__ import annotations

from .base import ReportCategory


class SecurityNotification(ReportCategory):
    """
    Routine ASX administrative notifications: unquoted securities,
    cessation of securities, Corporations Act 259C notices.
    No structured data is extracted — the DB record itself is the signal.
    """

    name = "SecurityNotification"

    _TITLE_KEYWORDS = [
        "notification regarding",
        "unquoted securities",
        "cessation of securities",
        "corporations act",
        "subsection 259c",
    ]
    _TEXT_KEYWORDS = ["unquoted", "cessation", "notification"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        return {}
