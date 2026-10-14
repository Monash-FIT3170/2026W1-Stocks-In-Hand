"""FinBERT's one input for an artifact: its title and source text, capped.

test_artifact_analysis.py checks every path that scores an artifact uses it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services import sentiment as sentiment_service

TITLE = "BHP lifts copper output"
RAW_TEXT = "BHP reported stronger copper production in its quarterly update."
EXPECTED = f"{TITLE}\n\n{RAW_TEXT}"


def test_input_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAX_ANALYSIS_CHARS", 10)

    assert sentiment_service.sentiment_input(TITLE, RAW_TEXT) == EXPECTED[:10]


def test_missing_title_or_text_does_not_leak_none() -> None:
    assert "None" not in sentiment_service.sentiment_input(None, RAW_TEXT)
    assert "None" not in sentiment_service.sentiment_input(TITLE, None)
