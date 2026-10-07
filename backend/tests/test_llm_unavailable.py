"""Analysis keeps sentiment when no LLM provider is available.

Before this was typed, the fallback string-matched "not configured", which only
the Groq adapter raised. With Bedrock disabled every analysis failed and was
retried instead of storing sentiment without a summary.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.generation import NewsSummary, Unavailable, generate, providers
from app.services.generation.providers import ScriptedProvider
from app.services.llm_errors import LLMUnavailableError
from parsing.analysis import analyse_news_text, analyse_public_discussion_text

SENTIMENT = {
    "sentiment_label": "negative",
    "label": "bearish",
    "confidence_score": 0.9,
    "model_used": "test-finbert",
}


@pytest.fixture(autouse=True)
def stub_finbert(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    analyse_text = MagicMock(return_value=SENTIMENT)
    monkeypatch.setattr("app.services.sentiment.analyse_text", analyse_text)
    return analyse_text


@pytest.fixture(params=["bedrock_disabled", "groq_without_key"])
def unavailable_provider(request: pytest.FixtureRequest):
    if request.param == "bedrock_disabled":
        overrides = {"LLM_PROVIDER": "bedrock", "BEDROCK_ENABLED": False}
    else:
        overrides = {"LLM_PROVIDER": "groq", "GROQ_API_KEY": ""}
    with patch.multiple(settings, **overrides):
        yield request.param


def _analyse(kind: str):
    if kind == "news":
        return analyse_news_text(
            title="BHP cuts guidance",
            raw_text="BHP lowered its copper guidance.",
            source_name="Publisher",
        )
    return analyse_public_discussion_text(
        title="$BHP guidance",
        raw_text="Guidance cut looks bad.",
        source_type="reddit",
    )


@pytest.mark.parametrize("kind", ["news", "public_discussion"])
def test_unavailable_provider_stores_sentiment_without_summary(
    unavailable_provider: str,
    kind: str,
) -> None:
    output = _analyse(kind)

    assert output.sentiment == SENTIMENT
    assert output.summary is None
    assert output.summary_model is None
    assert output.summary_prompt_version is None


def test_both_providers_report_unavailable(unavailable_provider: str) -> None:
    result = generate(
        NewsSummary(
            title="BHP cuts guidance",
            source_name=None,
            raw_text="BHP lowered its copper guidance.",
        )
    )

    assert isinstance(result, Unavailable)


def test_typed_error_stays_a_runtime_error_for_existing_route_handlers() -> None:
    assert issubclass(LLMUnavailableError, RuntimeError)


def test_provider_failures_are_still_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    failing = ScriptedProvider([RuntimeError("Amazon Bedrock model invocation failed")])
    monkeypatch.setattr(providers, "configured_provider", lambda: failing)

    with pytest.raises(RuntimeError, match="invocation failed"):
        _analyse("news")
