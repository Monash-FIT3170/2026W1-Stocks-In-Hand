from __future__ import annotations

import json

from .base import ReportCategory

_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
_MAX_TEXT = 12000


class QuarterlyTradingUpdate(ReportCategory):
    """Quarterly operational/trading update (e.g. ANZ 1Q FY2026 Trading Update)."""

    name = "QuarterlyTradingUpdate"

    _TITLE_KEYWORDS = ["quarterly", "trading update", "quarter update"]
    _TITLE_PATTERNS = ["1q", "2q", "3q", "4q", "q1", "q2", "q3", "q4"]
    _TEXT_KEYWORDS = ["quarterly", "quarter", "trading update"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        if client is None:
            raise ValueError(f"{cls.name}.extract() requires a Groq client")

        prompt = f"""\
You are a financial analyst extracting structured data from an ASX quarterly trading update.

Title: {title}

Report text:
{text[:_MAX_TEXT]}

Return JSON only, no explanation:
{{
  "period": "e.g. 1Q FY2026",
  "key_metrics": {{"metric_name": "value as string"}},
  "outlook": "1-2 sentence summary of forward-looking guidance",
  "raw_summary": "2-3 sentence plain-English summary"
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
