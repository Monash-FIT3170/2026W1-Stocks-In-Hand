"""Every path that scores an artifact gives FinBERT the same text.

The analysis worker scored title + raw_text, the admin news route scored
uncapped raw_text only, and the local loader scored title + the LLM summary,
so the same artifact could get three different sentiments.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import news_sentiment
from app.services import sentiment as sentiment_service
from app.services.generation import providers
from app.services.generation.providers import ScriptedProvider
from parsing import storage
from parsing.analysis import analyse_news_text

TITLE = "BHP lifts copper output"
RAW_TEXT = "BHP reported stronger copper production in its quarterly update."
EXPECTED = f"{TITLE}\n\n{RAW_TEXT}"
SENTIMENT = {
    "sentiment_label": "positive",
    "label": "positive",
    "confidence_score": 0.8,
    "model_used": "test-finbert",
}


@pytest.fixture()
def finbert(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    analyse_text = MagicMock(return_value=SENTIMENT)
    monkeypatch.setattr(sentiment_service, "analyse_text", analyse_text)
    return analyse_text


def _stored_artifact():
    return SimpleNamespace(
        id="artifact-1",
        title=TITLE,
        raw_text=RAW_TEXT,
        artifact_metadata={
            "summary": "Generated summary that must not be scored.",
            "about": "Generated about text.",
        },
    )


def test_worker_admin_route_and_local_loader_score_the_same_text(
    finbert: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_llm = ScriptedProvider([RuntimeError("summary not needed")])
    monkeypatch.setattr(providers, "configured_provider", lambda: failing_llm)
    with pytest.raises(RuntimeError, match="summary not needed"):
        analyse_news_text(title=TITLE, raw_text=RAW_TEXT)
    news_sentiment.analyse_news_artifact_sentiment(MagicMock(), _stored_artifact())
    local_input = storage._artifact_sentiment_text(_stored_artifact(), RAW_TEXT)

    scored = [call.args[0] for call in finbert.call_args_list]
    assert scored == [EXPECTED, EXPECTED]
    assert local_input == EXPECTED


def test_input_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_ANALYSIS_CHARS", "10")

    assert sentiment_service.sentiment_input(TITLE, RAW_TEXT) == EXPECTED[:10]


def test_missing_title_or_text_does_not_leak_none() -> None:
    assert "None" not in sentiment_service.sentiment_input(None, RAW_TEXT)
    assert "None" not in sentiment_service.sentiment_input(TITLE, None)
