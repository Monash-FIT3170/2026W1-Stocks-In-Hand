from __future__ import annotations

import re

from .base import ReportCategory


def _parse_date_slash(raw: str) -> str | None:
    """Convert D/M/YYYY or DD/MM/YYYY to ISO YYYY-MM-DD."""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw.strip())
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def _extract_3h(text: str) -> dict:
    """Appendix 3H — Notification of cessation of securities."""
    result: dict = {"appendix": "3H"}

    # Security code + description from summary table row: "ANZAA OPTIONS/RIGHTS 102,044 ..."
    m = re.search(r"([A-Z]{2,6})\s+(OPTIONS/RIGHTS|ORDINARY[^0-9]*?|PREFERENCE[^0-9]*?)\s+([\d,]+)", text)
    if m:
        result["security_code"] = m.group(1)
        result["security_description"] = m.group(2).strip()
        result["number_ceased"] = int(m.group(3).replace(",", ""))

    # Reason for cessation
    m = re.search(r"Reason for cessation\s*\n(.+?)(?:\n[A-Z]|\nDate)", text, re.DOTALL)
    if m:
        result["reason"] = m.group(1).strip()

    # Date of cessation
    m = re.search(r"Date of cessation\s*\n(\d{1,2}/\d{1,2}/\d{4})", text)
    if m:
        result["cessation_date"] = _parse_date_slash(m.group(1))

    return result


def _extract_3g(text: str) -> dict:
    """Appendix 3G — Notification of issue/conversion of unquoted equity securities."""
    result: dict = {"appendix": "3G"}

    # Security code, description, number issued, issue date from summary table
    # Pattern: "ANZ ORDINARY FULLY PAID 28,001 03/03/2026"
    m = re.search(r"([A-Z]{2,6})\s+(ORDINARY[^0-9]+?|OPTIONS/RIGHTS[^0-9]*?)\s+([\d,]+)\s+(\d{1,2}/\d{2}/\d{4})", text)
    if m:
        result["security_code"] = m.group(1)
        result["security_description"] = m.group(2).strip()
        result["number_issued"] = int(m.group(3).replace(",", ""))
        result["issue_date"] = _parse_date_slash(m.group(4))

    return result


class SecurityNotification(ReportCategory):
    """
    Routine ASX administrative notifications: unquoted securities,
    cessation of securities, Corporations Act 259C notices.
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
        if "Appendix 3H" in text:
            return _extract_3h(text)
        if "Appendix 3G" in text:
            return _extract_3g(text)
        # Corporations Act 259C or other administrative notices — no structured extraction
        return {}
