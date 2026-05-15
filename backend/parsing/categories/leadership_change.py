from __future__ import annotations

import re

from .base import ReportCategory

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_prose_date(raw: str) -> str | None:
    """Convert 'D Month YYYY' or 'DD Month YYYY' to ISO YYYY-MM-DD."""
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw.strip())
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}"
    return None


class LeadershipChange(ReportCategory):
    """Executive appointments, resignations, or senior management restructures."""

    name = "LeadershipChange"

    _TITLE_KEYWORDS = ["leadership", "appointment", "resign", "management change"]
    _TEXT_KEYWORDS = ["appointed", "resigned", "effective", "leadership"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        result: dict = {}
        text_lower = text.lower()

        # Change type
        has_appointment = "appointed" in text_lower or "appointment" in text_lower
        has_resignation = "resign" in text_lower or "leaving" in text_lower
        if has_appointment and has_resignation:
            result["change_type"] = "restructure"
        elif has_appointment:
            result["change_type"] = "appointment"
        elif has_resignation:
            result["change_type"] = "resignation"
        else:
            result["change_type"] = "restructure"

        # Person: "Firstname Lastname has been appointed ..."
        # Captures the first proper-case two-word name before "has been appointed"
        m = re.search(
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+has been (?:appointed|named)",
            text,
        )
        if m:
            result["person"] = m.group(1)
        else:
            # Fallback: person named after "appoint" keyword
            m = re.search(r"appoint(?:ed|ment of)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", text)
            if m:
                result["person"] = m.group(1)

        # Role: text after "appointed" up to "effective", comma, or end of clause
        m = re.search(r"has been appointed\s+([^,\n\.]{5,80}?)(?:\s+effective|\s+from|\s+,|\.|\n)", text)
        if m:
            result["role"] = m.group(1).strip()

        # Effective date: "effective D Month YYYY" or "effective from D Month YYYY"
        m = re.search(
            r"effective(?:\s+from)?\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            text,
            re.IGNORECASE,
        )
        if m:
            result["effective_date"] = _parse_prose_date(m.group(1))

        return result
