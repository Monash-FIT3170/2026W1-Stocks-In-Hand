from __future__ import annotations

import re
from datetime import datetime

from .base import ReportCategory

# Date format helpers
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_date(raw: str) -> str | None:
    """Convert various date formats to ISO YYYY-MM-DD, or return None."""
    raw = raw.strip()
    # DD/M/YYYY or D/MM/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    # D Month YYYY  (e.g. "1 July 2026", "11 May 2026")
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", raw)
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month:
            return f"{m.group(3)}-{month:02d}-{int(m.group(1)):02d}"
    return None


def _extract_appendix_3a1(text: str) -> dict:
    """Extract from ASX Appendix 3A.1 structured form."""
    result: dict = {}

    # Amount: "Distribution Amount\nAUD 0.83000000"
    m = re.search(r"Distribution Amount\s*\nAUD\s+([\d.]+)", text)
    if m:
        cents = round(float(m.group(1)) * 100)
        result["amount_per_share"] = f"{cents} cents"

    # Ex Date / Record Date / Payment Date from summary section
    for field, key in [("Ex Date", "ex_date"), ("Record Date", "record_date"), ("Payment Date", "payment_date")]:
        m = re.search(re.escape(field) + r"\s*\n(\d{1,2}/\d{1,2}/\d{4})", text)
        if m:
            result[key] = _parse_date(m.group(1))

    # Dividend type: "relates to a period of six months" → interim, "twelve months" → final
    if "six months" in text:
        result["dividend_type"] = "interim"
    elif "twelve months" in text or "final" in text.lower()[:500]:
        result["dividend_type"] = "final"

    # Franking: "3A.3 Percentage of ordinary dividend/distribution that is\nfranked\n75.0000 %"
    m = re.search(r"Percentage[^\n]+\nfranked\n([\d.]+)\s*%", text)
    if m:
        result["franking_percent"] = f"{float(m.group(1)):.0f}%"
    elif "fully franked" in text.lower():
        result["franking_percent"] = "100%"

    return result


def _extract_news_release(title: str, text: str) -> dict:
    """Extract from News Release prose format."""
    result: dict = {}

    # Amount: "83  cents per share" or "83 cents per share"
    m = re.search(r"(\d[\d\s]*?)\s+cents?\s+per\s+share", text, re.IGNORECASE)
    if m:
        amount = m.group(1).replace(" ", "")
        result["amount_per_share"] = f"{amount} cents"

    # Franking: "partially franked at 75%" or "fully franked"
    m = re.search(r"partially franked at\s+([\d]+)\s*%", text, re.IGNORECASE)
    if m:
        result["franking_percent"] = f"{m.group(1)}%"
    elif re.search(r"\bfully franked\b", text, re.IGNORECASE):
        result["franking_percent"] = "100%"

    # Dividend type: interim / final from title then text
    combined = (title + " " + text[:500]).lower()
    if "interim" in combined:
        result["dividend_type"] = "interim"
    elif "final" in combined:
        result["dividend_type"] = "final"

    # Dates: "Ex-date  Monday , 11 May 2026" or "Ex Date  Monday , 11 May 2026"
    m = re.search(r"Ex[-\s]date\s+\w+\s*,\s*(\d{1,2}\s+\w+\s+\d{4})", text, re.IGNORECASE)
    if m:
        result["ex_date"] = _parse_date(m.group(1))

    m = re.search(r"Record Date\s+\w+\s*,\s*(\d{1,2}\s+\w+\s+\d{4})", text, re.IGNORECASE)
    if m:
        result["record_date"] = _parse_date(m.group(1))

    # Payment date: may appear as "Dividend Payment Date ... Wednesday , 1 July 2026"
    m = re.search(r"Payment Date\b.*?(\d{1,2}\s+\w+\s+\d{4})", text, re.IGNORECASE | re.DOTALL)
    if m:
        result["payment_date"] = _parse_date(m.group(1))

    return result


class DividendAnnouncement(ReportCategory):
    """Dividend declaration, distribution notice, or interim dividend key dates."""

    name = "DividendAnnouncement"

    _TITLE_KEYWORDS = ["dividend", "distribution", "franking"]
    _TEXT_KEYWORDS = ["dividend", "ex-dividend", "payment date", "record date", "franking"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        if "Appendix 3A.1" in text:
            return _extract_appendix_3a1(text)
        return _extract_news_release(title, text)
