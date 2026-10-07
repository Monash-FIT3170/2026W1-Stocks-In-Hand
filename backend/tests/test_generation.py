"""Structured generation through its public interface, with a scripted provider."""

from __future__ import annotations

import json

import pytest

from app.services import llm
from app.services.generation import providers
from app.services.generation.providers import ScriptedProvider

ANNOUNCEMENT_SUMMARY = {
    "summary": "The company announced an update.",
    "about": "The filing describes the update.",
    "changed": "The update was confirmed.",
    "matters": "Investors can assess the confirmed change.",
    "confirmed_facts": ["The company confirmed the update."],
    "speculation": [],
}


@pytest.fixture()
def scripted(monkeypatch: pytest.MonkeyPatch):
    """Install a scripted provider as the configured one."""

    def install(*responses: str | Exception) -> ScriptedProvider:
        provider = ScriptedProvider(list(responses))
        monkeypatch.setattr(providers, "configured_provider", lambda: provider)
        return provider

    return install


def _summarise_announcement() -> dict[str, object]:
    return llm.summarise_announcement(
        title="Company update",
        category="organisational",
        extracted_data={},
        raw_text="The company confirmed an update.",
    )


def test_valid_json_takes_one_call(scripted) -> None:
    provider = scripted(json.dumps(ANNOUNCEMENT_SUMMARY))

    assert _summarise_announcement() == ANNOUNCEMENT_SUMMARY
    assert len(provider.calls) == 1


def test_malformed_json_is_repaired_once(scripted) -> None:
    """A formatting defect must not discard otherwise recoverable analysis."""
    malformed = '{"summary": "An update"'
    provider = scripted(malformed, json.dumps(ANNOUNCEMENT_SUMMARY))

    assert _summarise_announcement()["summary"] == "The company announced an update."
    repair = provider.calls[1]
    assert json.dumps(malformed, ensure_ascii=False) in repair.prompt
    assert repair.temperature == 0


def test_a_malformed_repair_is_retried_once(scripted) -> None:
    truncated_repair = '{\n  "summary": "The company announced an update.'
    provider = scripted(
        '{"summary": "An update"',
        truncated_repair,
        json.dumps(ANNOUNCEMENT_SUMMARY),
    )

    assert _summarise_announcement()["summary"] == "The company announced an update."
    assert len(provider.calls) == 3
    assert json.dumps(truncated_repair, ensure_ascii=False) in provider.calls[2].prompt
    assert provider.calls[2].temperature == 0


def test_repair_gives_up_after_two_attempts(scripted) -> None:
    provider = scripted('{"summary": "An update"', "not json", "still not json")

    with pytest.raises(ValueError):
        _summarise_announcement()

    assert len(provider.calls) == 3


def test_summary_parser_quotes_only_known_unquoted_keys() -> None:
    """GPT-OSS's known key-quoting defect is repaired without weakening the schema."""
    result = llm.parse_summary_response(
        """
        {
          summary: "The company announced an update.",
          about: "The filing describes the update.",
          changed: "The update was confirmed.",
          matters: "Investors can assess the confirmed change.",
          confirmed_facts: ["The company confirmed the update."],
          speculation: []
        }
        """
    )

    assert result["summary"] == "The company announced an update."
    with pytest.raises(json.JSONDecodeError):
        llm.parse_summary_response('{\n  arbitrary_key: "This key is not allowed."\n}')


def test_summary_parser_removes_one_redundant_opening_brace() -> None:
    """GPT-OSS may wrap an otherwise valid object with one unmatched brace."""
    result = llm.parse_summary_response("{\n" + json.dumps(ANNOUNCEMENT_SUMMARY))

    assert result["summary"] == "The company announced an update."
    with pytest.raises(json.JSONDecodeError):
        llm.parse_summary_response('{{{"summary": "Too many wrappers"}')


def test_category_split_reads_the_configured_provider(scripted) -> None:
    provider = scripted(
        json.dumps(
            {
                "revenue": "Revenue increased.",
                "strategy": "",
                "risk": "",
                "dividend": "",
                "organisational": "",
            }
        )
    )

    result = llm.categorise_chunk("Revenue increased during the half year.")

    assert result["revenue"] == "Revenue increased."
    assert llm.active_model_name() == provider.name


def test_reddit_digest_rejects_an_unrecognised_sentiment(scripted) -> None:
    scripted('{"summary":"A summary","dominant_sentiment":"excited","key_themes":[]}')

    with pytest.raises(ValueError, match="sentiment was not recognised"):
        llm.summarise_reddit_digest(
            ticker_symbol="BHP",
            posts=[{"title": "BHP", "body": "", "score": 1}],
        )
