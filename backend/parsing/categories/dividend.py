from __future__ import annotations

import json

from .base import ReportCategory

_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
_MAX_TEXT = 8000


class DividendAnnouncement(ReportCategory):
    """Dividend declaration, distribution notice, or interim dividend key dates."""

    name = "DividendAnnouncement"

    _TITLE_KEYWORDS = ["dividend", "distribution", "franking"]
    _TEXT_KEYWORDS = ["dividend", "ex-dividend", "payment date", "record date", "franking"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        """
        Uses LLM if client is provided (more accurate for amounts and dates).
        Returns an empty dict if no client — dividend key-date PDFs are
        heavily table-formatted and unreliable to parse with simple rules.
        """
        if client is None:
            return {}

        prompt = f"""\
You are a financial analyst extracting dividend details from an ASX announcement.

Title: {title}

Report text:
{text[:_MAX_TEXT]}

Return JSON only, no explanation:
{{
  "dividend_type": "interim or final",
  "amount_per_share": "e.g. 83 cents",
  "ex_date": "e.g. 2026-05-14 or null",
  "record_date": "e.g. 2026-05-15 or null",
  "payment_date": "e.g. 2026-07-01 or null",
  "franking_percent": "e.g. 100% or null"
}}"""

        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        try:
            result = json.loads(raw)
            return result if isinstance(result, dict) else {"raw_response": raw}
        except json.JSONDecodeError:
            return {"raw_response": raw}
