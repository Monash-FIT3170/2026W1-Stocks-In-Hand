"""Structured generation through ``generate``, with a scripted provider.

The Groq scenario uses the real Groq adapter over an httpx mock transport, to
show both providers now get a prompt that fits instead of Groq cutting the
end off one.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from app.core.config import settings
from app.services import generation
from app.services.generation import (
    AnnouncementSummary,
    CategorySplit,
    DiscussionSummary,
    Generated,
    NewsSummary,
    RedditDigest,
    Unavailable,
    generate,
    providers,
)
from app.services.generation.groq import GROQ_RETRY_PROMPT_CHARS, GroqProvider
from app.services.generation.providers import ScriptedProvider
from app.services.llm_errors import LLMUnavailableError

ANNOUNCEMENT_SUMMARY = {
    "summary": "The company announced an update.",
    "about": "The filing describes the update.",
    "changed": "The update was confirmed.",
    "matters": "Investors can assess the confirmed change.",
    "confirmed_facts": ["The company confirmed the update."],
    "speculation": [],
}
CATEGORIES = {
    "revenue": "Revenue increased.",
    "strategy": "",
    "risk": "",
    "dividend": "",
    "organisational": "",
}
DIGEST = {"summary": "Investors are mixed.", "dominant_sentiment": "mixed", "key_themes": []}


def _announcement(raw_text: str = "The company confirmed an update.") -> AnnouncementSummary:
    return AnnouncementSummary(
        title="Company update",
        category="organisational",
        extracted_data={},
        raw_text=raw_text,
    )


def _digest(body: str = "Iron ore demand looks soft.", count: int = 1) -> RedditDigest:
    return RedditDigest(
        ticker_symbol="BHP",
        posts=[{"title": f"BHP post {index}", "body": body, "score": 3} for index in range(count)],
    )


def _example(kind: type, text: str):
    return {
        AnnouncementSummary: lambda: _announcement(text),
        NewsSummary: lambda: NewsSummary(title="Story", source_name=None, raw_text=text),
        DiscussionSummary: lambda: DiscussionSummary(
            title="Post",
            source_type="reddit",
            raw_text=text,
        ),
        RedditDigest: lambda: _digest(text, count=60),
        CategorySplit: lambda: CategorySplit(text),
    }[kind]()


ALL_KINDS = (AnnouncementSummary, NewsSummary, DiscussionSummary, RedditDigest, CategorySplit)


def test_a_valid_answer_records_the_model_and_prompt_version() -> None:
    provider = ScriptedProvider([json.dumps(ANNOUNCEMENT_SUMMARY)])

    result = generate(_announcement(), provider=provider)

    assert result == Generated(
        value=ANNOUNCEMENT_SUMMARY,
        model="scripted:test-model",
        prompt_version="llm-announcement-summary-v3",
    )
    [call] = provider.calls
    assert call.temperature == 0.2
    assert call.max_output_tokens == AnnouncementSummary.budget.output_tokens


def test_generate_uses_the_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ScriptedProvider([json.dumps(CATEGORIES)], name="scripted:configured")
    monkeypatch.setattr(providers, "configured_provider", lambda: provider)

    result = generate(CategorySplit("Revenue increased during the half year."))

    assert result.value["revenue"] == "Revenue increased."
    assert result.model == "scripted:configured"


def test_an_unavailable_provider_is_an_explicit_result() -> None:
    provider = ScriptedProvider([LLMUnavailableError("Amazon Bedrock is disabled")])

    assert generate(_announcement(), provider=provider) == Unavailable(
        "Amazon Bedrock is disabled"
    )


def test_a_failed_call_is_raised_for_a_retry() -> None:
    provider = ScriptedProvider([RuntimeError("Amazon Bedrock model invocation failed")])

    with pytest.raises(RuntimeError, match="invocation failed"):
        generate(_announcement(), provider=provider)


def test_malformed_json_is_repaired_once() -> None:
    """A formatting defect must not discard otherwise recoverable analysis."""
    malformed = '{"summary": "An update"'
    provider = ScriptedProvider([malformed, json.dumps(ANNOUNCEMENT_SUMMARY)])

    result = generate(_announcement(), provider=provider)

    assert result.value == ANNOUNCEMENT_SUMMARY
    assert result.prompt_version == "llm-announcement-summary-v3"
    repair = provider.calls[1]
    assert json.dumps(malformed, ensure_ascii=False) in repair.prompt
    assert repair.temperature == 0


def test_a_malformed_repair_is_retried_once() -> None:
    truncated_repair = '{\n  "summary": "The company announced an update.'
    provider = ScriptedProvider(
        ['{"summary": "An update"', truncated_repair, json.dumps(ANNOUNCEMENT_SUMMARY)]
    )

    assert generate(_announcement(), provider=provider).value == ANNOUNCEMENT_SUMMARY
    assert len(provider.calls) == 3
    assert json.dumps(truncated_repair, ensure_ascii=False) in provider.calls[2].prompt


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ('{"summary": "Only one field"}', "missing keys"),
        (
            json.dumps({**ANNOUNCEMENT_SUMMARY, "confirmed_facts": "Not a list."}),
            "confirmed_facts.*list of strings",
        ),
    ],
)
def test_repair_gives_up_after_two_attempts(answer: str, error: str) -> None:
    provider = ScriptedProvider([answer, answer, answer])

    with pytest.raises(ValueError, match=error):
        generate(_announcement(), provider=provider)

    assert len(provider.calls) == 3


def test_known_gpt_oss_defects_are_fixed_without_a_repair_call() -> None:
    unquoted = "{\n" + "\n".join(
        f"  {key}: {json.dumps(value)}," for key, value in ANNOUNCEMENT_SUMMARY.items()
    ).rstrip(",") + "\n}"
    extra_brace = "{\n" + json.dumps(ANNOUNCEMENT_SUMMARY)
    provider = ScriptedProvider([unquoted, extra_brace])

    assert generate(_announcement(), provider=provider).value == ANNOUNCEMENT_SUMMARY
    assert generate(_announcement(), provider=provider).value == ANNOUNCEMENT_SUMMARY
    assert len(provider.calls) == 2


def test_unknown_unquoted_keys_still_need_a_repair() -> None:
    provider = ScriptedProvider(
        ['{\n  arbitrary_key: "Not allowed."\n}', json.dumps(ANNOUNCEMENT_SUMMARY)]
    )

    assert generate(_announcement(), provider=provider).value == ANNOUNCEMENT_SUMMARY
    assert len(provider.calls) == 2


def test_a_digest_has_no_repair() -> None:
    provider = ScriptedProvider(
        ['{"summary":"A summary","dominant_sentiment":"excited","key_themes":[]}']
    )

    with pytest.raises(ValueError, match="sentiment was not recognised"):
        generate(_digest(), provider=provider)

    assert len(provider.calls) == 1


def test_news_and_discussion_summaries_have_no_clarity_lists() -> None:
    four_fields = {key: ANNOUNCEMENT_SUMMARY[key] for key in generation.SUMMARY_TEXT_KEYS}
    provider = ScriptedProvider([json.dumps(four_fields), json.dumps(four_fields)])

    news = generate(NewsSummary(title="Story", source_name="Wire", raw_text="Text"), provider=provider)
    post = generate(
        DiscussionSummary(title="Post", source_type="bluesky", raw_text="Text"),
        provider=provider,
    )

    assert news.value == four_fields
    assert news.prompt_version == "llm-news-summary-v2"
    assert post.value == four_fields
    assert post.prompt_version == "llm-public-discussion-summary-v2"


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda kind: kind.__name__)
def test_every_kind_cuts_its_source_text_to_its_input_budget(kind: type) -> None:
    budget = kind.budget.input_chars
    example = _example(kind, "x" * (budget * 2))
    answer = {
        AnnouncementSummary: ANNOUNCEMENT_SUMMARY,
        RedditDigest: DIGEST,
        CategorySplit: CATEGORIES,
    }.get(kind, {key: "text" for key in generation.SUMMARY_TEXT_KEYS})
    provider = ScriptedProvider([json.dumps(answer)])

    generate(example, provider=provider)

    [call] = provider.calls
    assert call.prompt == example.prompt(example.source_text[:budget])
    assert call.max_output_tokens == kind.budget.output_tokens


@pytest.mark.parametrize("kind", ALL_KINDS, ids=lambda kind: kind.__name__)
def test_every_kind_fits_the_default_bedrock_prompt_limit(kind: type) -> None:
    example = _example(kind, "x" * (kind.budget.input_chars * 2))

    prompt = example.prompt(example.source_text[: kind.budget.input_chars])

    assert len(prompt) <= 30000


def test_a_prompt_the_provider_refuses_is_refitted_with_the_instructions_kept() -> None:
    provider = ScriptedProvider(
        [json.dumps({key: "text" for key in generation.SUMMARY_TEXT_KEYS})],
        max_prompt_chars=2000,
    )
    story = NewsSummary(title="Story", source_name=None, raw_text="word " * 2000)

    generate(story, provider=provider)

    refused, accepted = provider.calls
    assert len(refused.prompt) > 2000
    assert 1990 <= len(accepted.prompt) <= 2000
    assert accepted.prompt.startswith("You are summarising a financial news story")
    assert "Return strict JSON only" in accepted.prompt


def test_groq_payload_rejection_keeps_the_digest_instructions() -> None:
    """Groq used to cut the prompt's end, which holds a digest's answer format."""
    bodies: list[dict] = []
    responses = [
        httpx.Response(413),
        httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(DIGEST)}}]}),
    ]

    def server(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return responses.pop(0)

    with patch.multiple(settings, GROQ_API_KEY="test-key"):
        result = generate(
            _digest("Long post. " * 30, count=40),
            provider=GroqProvider(httpx.MockTransport(server)),
        )

    assert result.value == DIGEST
    retried = bodies[1]["messages"][0]["content"]
    assert len(retried) <= GROQ_RETRY_PROMPT_CHARS
    assert retried.endswith("key_themes: an array of short recurring themes.")


def test_a_category_split_in_batches_joins_each_category() -> None:
    chunk = generation.kinds.ARTIFACT_SEPARATOR.join(["First", "Second", "Third"])
    provider = ScriptedProvider(
        [
            json.dumps({**CATEGORIES, "risk": "Risk one."}),
            json.dumps({**CATEGORIES, "revenue": "", "risk": "Risk two."}),
        ]
    )

    result = generate(CategorySplit(chunk, batch_size=2), provider=provider)

    assert result.value == {**CATEGORIES, "risk": "Risk one.\n\nRisk two."}
    assert result.prompt_version == "llm-category-v2"
    assert "First" in provider.calls[0].prompt and "Second" in provider.calls[0].prompt
    assert "Third" in provider.calls[1].prompt
