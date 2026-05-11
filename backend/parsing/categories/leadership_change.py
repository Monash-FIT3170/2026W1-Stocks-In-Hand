from __future__ import annotations

import json

from .base import ReportCategory

_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
_MAX_TEXT = 6000


class LeadershipChange(ReportCategory):
    """Executive appointments, resignations, or senior management restructures."""

    name = "LeadershipChange"

    _TITLE_KEYWORDS = ["leadership", "appointment", "resign", "management change"]
    _TEXT_KEYWORDS = ["appointed", "resigned", "effective", "leadership"]

    @classmethod
    def extract(cls, title: str, text: str, client=None) -> dict:
        """Uses LLM if available; returns empty dict in rule-only mode."""
        if client is None:
            return {}

        prompt = f"""\
You are a financial analyst extracting details from an ASX leadership change announcement.

Title: {title}

Report text:
{text[:_MAX_TEXT]}

Return JSON only, no explanation:
{{
  "change_type": "e.g. appointment, resignation, restructure",
  "role": "job title(s) affected",
  "person": "name(s) of individual(s) or null",
  "effective_date": "e.g. 2026-04-01 or null"
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
