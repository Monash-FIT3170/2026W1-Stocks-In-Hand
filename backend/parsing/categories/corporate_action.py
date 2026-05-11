from __future__ import annotations

import json

from .base import ReportCategory

_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
_MAX_TEXT = 10000


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
        if client is None:
            raise ValueError(f"{cls.name}.extract() requires a Groq client")

        prompt = f"""\
You are a financial analyst extracting details from an ASX corporate action announcement.

Title: {title}

Report text:
{text[:_MAX_TEXT]}

Return JSON only, no explanation:
{{
  "action_type": "e.g. acquisition, divestment, merger, JV change",
  "counterparty": "name of the other party or null",
  "deal_value": "deal size with currency or null",
  "rationale": "1-2 sentence summary of the strategic rationale"
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
