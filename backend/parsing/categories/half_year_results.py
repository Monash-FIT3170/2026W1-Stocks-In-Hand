from __future__ import annotations

import json

from .base import ReportCategory

_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
_MAX_TEXT = 12000


class HalfYearResults(ReportCategory):
    """Half-year (interim) financial results announcement."""

    name = "HalfYearResults"

    _TITLE_KEYWORDS = [
        "half year", "half-year", "interim results", "interim",
        "appendix 4d", "half year result",
    ]
    _TITLE_PATTERNS = ["1h", "2h", "h1", "h2"]
    _TEXT_KEYWORDS = ["half year", "half-year", "interim", "six months"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        if client is None:
            raise ValueError(f"{cls.name}.extract() requires a Groq client")

        prompt = f"""\
You are a financial analyst extracting structured data from an ASX half-year (interim) results announcement.

Title: {title}

Report text:
{text[:_MAX_TEXT]}

Return JSON only, no explanation:
{{
  "period": "e.g. 1H FY2026",
  "revenue": "total revenue with currency e.g. $10.2B",
  "npat": "net profit after tax with currency",
  "eps": "earnings per share with units e.g. 145.2 cents",
  "dividend": "dividend per share declared, or null if not mentioned",
  "key_highlights": ["bullet 1", "bullet 2", "bullet 3"]
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
