"""The content topic LLM kind and how its answer and the rules decide an artifact's topics.

A scripted provider stands in for the LLM. Nothing here reaches a database.
"""

import json

import pytest

from app.services import generation
from app.services.content_topics import (
    AGREEMENT_BONUS,
    TOPIC_DESCRIPTIONS,
    decide_topics,
)
from app.services.generation.kinds import (
    MAX_TAGGED_TOPICS,
    UNSUPPORTED_TOPIC_FACTOR,
    parse_topic_tagging_response,
)
from app.services.generation.providers import ScriptedProvider
from app.services.llm_errors import LLMUnavailableError
from parsing.content_topics import RULES_VERSION, TopicInput

SOURCE = (
    "The Company reported net profit after tax of $412 million. "
    "The Company reaffirms its full year guidance. "
    "A shareholder class action was filed in the Federal Court."
)
TOPICS = [topic for topic, _description in TOPIC_DESCRIPTIONS]


def _parse(answer: object) -> list[dict[str, object]]:
    return parse_topic_tagging_response(json.dumps(answer), topics=TOPICS, raw_text=SOURCE)


def _kind(**values) -> generation.TopicTagging:
    return generation.TopicTagging(
        **{
            "title": "Half Year Results",
            "source_type": "asx_announcement",
            "raw_text": SOURCE,
            "topics": TOPIC_DESCRIPTIONS,
            "hints": ("earnings_guidance",),
            **values,
        }
    )


def test_a_topic_with_a_verified_quotation_keeps_its_confidence() -> None:
    [topic] = _parse(
        {
            "topics": [
                {
                    "topic": "earnings_guidance",
                    "confidence": 0.9,
                    "passage": "The Company  reaffirms its full year GUIDANCE.",
                    "event": "  FY guidance   reaffirmed ",
                }
            ]
        }
    )

    assert topic == {
        "topic": "earnings_guidance",
        "confidence": 0.9,
        # The source's own wording, found despite spacing and case.
        "passage": "The Company reaffirms its full year guidance.",
        "event": "FY guidance reaffirmed",
    }


def test_a_quotation_not_in_the_source_is_dropped_and_lowers_the_confidence() -> None:
    [topic] = _parse(
        {"topics": [{"topic": "litigation", "confidence": 0.8, "passage": "Invented words."}]}
    )

    assert topic["passage"] is None
    assert topic["confidence"] == pytest.approx(0.8 * UNSUPPORTED_TOPIC_FACTOR)
    assert topic["event"] is None


def test_unknown_topics_and_bad_confidences_are_dropped_not_fatal() -> None:
    topics = _parse(
        {
            "topics": [
                {"topic": "mergers", "confidence": 0.9},
                {"topic": "litigation", "confidence": 1.5},
                {"topic": "litigation", "confidence": True},
                {"topic": "regulation", "confidence": "high"},
                "not an object",
                {"topic": "earnings_guidance", "confidence": 0.7},
            ]
        }
    )

    assert [topic["topic"] for topic in topics] == ["earnings_guidance"]


def test_each_topic_is_kept_once_at_its_best_and_at_most_three_are_kept() -> None:
    topics = _parse(
        {
            "topics": [
                {"topic": "litigation", "confidence": 0.4},
                {"topic": "litigation", "confidence": 0.7},
                {"topic": "earnings_guidance", "confidence": 0.9},
                {"topic": "regulation", "confidence": 0.5},
                {"topic": "macro_exposure", "confidence": 0.6},
            ]
        }
    )

    assert len(topics) == MAX_TAGGED_TOPICS
    assert [topic["topic"] for topic in topics] == [
        "earnings_guidance",
        "litigation",
        "macro_exposure",
    ]
    assert topics[1]["confidence"] == pytest.approx(0.7 * UNSUPPORTED_TOPIC_FACTOR)


@pytest.mark.parametrize(
    "answer",
    ["not json", "[]", '{"topics": {}}', '{"topics": [], "extra": 1}', "{}"],
)
def test_a_malformed_answer_is_a_value_error(answer: str) -> None:
    with pytest.raises(ValueError):
        parse_topic_tagging_response(answer, topics=TOPICS, raw_text=SOURCE)


def test_an_empty_list_means_no_topic() -> None:
    assert _parse({"topics": []}) == []


def test_the_prompt_lists_every_topic_the_hints_and_the_item() -> None:
    provider = ScriptedProvider([json.dumps({"topics": []})])

    result = generation.generate(_kind(), provider=provider)

    assert isinstance(result, generation.Generated)
    assert result.prompt_version == "llm-content-topics-v1"
    assert result.value == []
    [call] = provider.calls
    for topic, description in TOPIC_DESCRIPTIONS:
        assert f"- {topic}: {description}" in call.prompt
    assert "Rules-based hints, which may be wrong: earnings_guidance" in call.prompt
    assert call.prompt.endswith(SOURCE)
    assert (call.temperature, call.max_output_tokens) == (0, 2048)


def test_the_source_text_is_cut_to_the_kind_budget() -> None:
    provider = ScriptedProvider([json.dumps({"topics": []})])
    long_text = "x" * 20000

    generation.generate(_kind(raw_text=long_text), provider=provider)

    [call] = provider.calls
    assert "x" * 12000 in call.prompt
    assert "x" * 12001 not in call.prompt


def _source(**values) -> TopicInput:
    return TopicInput(
        **{
            "title": "Half Year Results",
            "text": SOURCE,
            "category": "HalfYearResults",
            "source_type": "asx_announcement",
            **values,
        }
    )


def test_the_llm_decides_and_a_topic_the_rules_agree_on_gains_the_bonus() -> None:
    provider = ScriptedProvider(
        [
            json.dumps(
                {
                    "topics": [
                        {
                            "topic": "litigation",
                            "confidence": 0.7,
                            "passage": "A shareholder class action was filed in the Federal Court.",
                            "event": "Shareholder class action filed",
                        },
                        {"topic": "macro_exposure", "confidence": 0.3},
                    ]
                }
            )
        ]
    )

    decision = decide_topics(_source(), provider=provider, use_llm=True, min_confidence=0.5)

    assert (decision.method, decision.version, decision.model) == (
        "llm",
        "llm-content-topics-v1",
        "scripted:test-model",
    )
    by_topic = {record.topic: record for record in decision.topics}
    # The rules found litigation too, from the Federal Court and class action phrases.
    assert by_topic["litigation"].confidence == pytest.approx(0.7 + AGREEMENT_BONUS)
    assert by_topic["litigation"].method == "llm"
    assert by_topic["litigation"].event_label == "Shareholder class action filed"
    # The LLM missed earnings, but a results category with its words is a strong rule.
    assert by_topic["earnings_guidance"].method == "rules"
    assert by_topic["earnings_guidance"].confidence >= 0.8
    # Below the recording threshold.
    assert "macro_exposure" not in by_topic
    assert [record.confidence for record in decision.topics] == sorted(
        (record.confidence for record in decision.topics), reverse=True
    )


def test_with_no_llm_switched_on_the_rules_decide() -> None:
    provider = ScriptedProvider([LLMUnavailableError("Bedrock is disabled")])

    decision = decide_topics(_source(), provider=provider, use_llm=True, min_confidence=0.5)

    assert (decision.method, decision.version, decision.model) == ("rules", RULES_VERSION, None)
    assert decision.llm_error is None
    assert {record.topic for record in decision.topics} >= {"earnings_guidance"}
    assert all(record.method == "rules" for record in decision.topics)


def test_a_malformed_answer_falls_back_to_the_rules_and_says_why() -> None:
    provider = ScriptedProvider(["not json"])

    decision = decide_topics(_source(), provider=provider, use_llm=True, min_confidence=0.5)

    assert decision.method == "rules"
    assert decision.llm_error == "JSONDecodeError"
    assert len(provider.calls) == 1


def test_a_failed_call_falls_back_to_the_rules() -> None:
    provider = ScriptedProvider([RuntimeError("throttled")])

    decision = decide_topics(_source(), provider=provider, use_llm=True, min_confidence=0.5)

    assert (decision.method, decision.llm_error) == ("rules", "RuntimeError")


def test_the_llm_is_not_asked_when_switched_off_or_when_there_is_no_text() -> None:
    provider = ScriptedProvider([])

    off = decide_topics(_source(), provider=provider, use_llm=False, min_confidence=0.5)
    empty = decide_topics(_source(text="  "), provider=provider, use_llm=True, min_confidence=0.5)

    assert provider.calls == []
    assert off.method == empty.method == "rules"


def test_only_topics_at_the_threshold_are_recorded() -> None:
    decision = decide_topics(_source(), use_llm=False, min_confidence=0.99)

    assert decision.topics == ()
