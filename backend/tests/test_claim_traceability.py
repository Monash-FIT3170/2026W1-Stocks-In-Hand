"""Regression tests for claim quotations and source validation."""

import json
from unittest.mock import MagicMock

import pytest

from app.services import artifact_summary, generation
from app.services.generation import kinds
from app.services.generation.providers import ScriptedProvider
from app.services.claim_traceability import exact_source_passage, validated_claim_evidence, traceable_claims, safe_source_url


@pytest.mark.parametrize("passage", [None, "", "Made-up revenue.", 123])
def test_source_passage_rejects_missing_or_invented_text(passage: object) -> None:
    assert exact_source_passage("Revenue rose this year.", passage) is None


def test_source_passage_preserves_case_and_normalises_document_whitespace() -> None:
    passage = exact_source_passage("Revenue\nrose   this year.", "revenue rose this year.")
    assert passage == "Revenue rose this year."


def test_announcement_summary_keeps_only_verified_evidence_for_current_claims() -> None:
    passage = "Revenue totalled $112 million, up from $100 million last year."
    response = {
        "summary": "Revenue rose.",
        "about": "Annual results.",
        "changed": "Revenue increased by 12%.",
        "matters": "Investors can assess the results.",
        "confirmed_facts": ["Revenue increased by 12%."],
        "speculation": ["Growth may continue."],
        "claim_evidence": [
            {
                "text": "Revenue increased by 12%.",
                "kind": "confirmed_fact",
                "passage": passage,
            },
            {
                "text": "Growth may continue.",
                "kind": "speculation",
                "passage": "Management expects further growth.",
            },
            {
                "text": "An unrelated claim.",
                "kind": "confirmed_fact",
                "passage": passage,
            },
            {
                "text": "Revenue increased by 12%.",
                "kind": "speculation",
                "passage": passage,
            },
            {"text": 123, "kind": "confirmed_fact", "passage": passage},
            {"text": "", "kind": "confirmed_fact", "passage": passage},
            None,
        ],
    }
    provider = ScriptedProvider([json.dumps(response)])
    summary = generation.generate(
        generation.AnnouncementSummary(
            title="Results", category="revenue", extracted_data={}, raw_text=passage,
        ),
        provider=provider,
    ).value

    assert summary["confirmed_facts"] == response["confirmed_facts"]
    assert summary["claim_evidence"] == response["claim_evidence"][:1]
    assert "verbatim supporting quotation" in provider.calls[0].prompt
    assert validated_claim_evidence(summary, "An unrelated replacement document.") == []


def test_summary_parser_rejects_malformed_evidence_container() -> None:
    response = dict.fromkeys(generation.SUMMARY_TEXT_KEYS, "An update.")
    response.update(confirmed_facts=[], speculation=[], claim_evidence="not a list")
    with pytest.raises(ValueError, match="claim_evidence must be a list"):
        kinds.parse_summary_response(json.dumps(response))


def _clarity_for_artifact(artifact):
    summary = artifact_summary.from_answer(artifact.artifact_metadata, model=None, prompt_version=None)
    return {**artifact_summary.clarity(summary), "traceable_claims": traceable_claims(artifact, summary)}


def test_claim_traceability_only_labels_a_verbatim_document_passage_as_exact() -> None:
    """Paraphrased claims must not be presented as exact source quotations."""
    from datetime import datetime, timezone


    artifact = MagicMock()
    artifact.artifact_metadata = {
        "confirmed_facts": ["Revenue increased by 12%."],
        "speculation": ["Revenue may continue growing."],
    }
    artifact.raw_text = "Results update: Revenue increased by 12%. Outlook remains uncertain."
    artifact.source_type = "asx_announcement"
    artifact.title = "Results update"
    artifact.document_url = "https://example.test/results.pdf"
    artifact.canonical_url = "https://example.test/results"
    artifact.url = "https://example.test/legacy"
    artifact.published_at = datetime(2040, 2, 3, tzinfo=timezone.utc)

    result = _clarity_for_artifact(artifact)

    exact_source = result["traceable_claims"][0]["source"]
    paraphrase_source = result["traceable_claims"][1]["source"]
    assert exact_source["url"] == "https://example.test/results.pdf"
    assert exact_source["published_at"] == "2040-02-03T00:00:00+00:00"
    assert exact_source["evidence_text"] == "Revenue increased by 12%."
    assert paraphrase_source["evidence_text"] is None


def test_claim_traceability_rejects_unsafe_source_urls() -> None:
    """Unsafe source schemes must never become clickable frontend citations."""

    artifact = MagicMock()
    artifact.artifact_metadata = {
        "confirmed_facts": ["A claim."],
        "speculation": [],
    }
    artifact.raw_text = "A claim."
    artifact.source_type = "news"
    artifact.title = "Unsafe source"
    artifact.document_url = "javascript:alert(1)"
    artifact.canonical_url = None
    artifact.url = None
    artifact.published_at = None

    result = _clarity_for_artifact(artifact)

    assert result["traceable_claims"][0]["source"] is None


def test_claim_traceability_falls_back_to_the_next_safe_source_url() -> None:
    """A bad direct-document URL should not hide a valid canonical source."""

    artifact = MagicMock()
    artifact.artifact_metadata = {
        "confirmed_facts": ["A claim."],
        "speculation": [],
    }
    artifact.raw_text = "A claim."
    artifact.source_type = "news"
    artifact.title = "Safe fallback"
    artifact.document_url = "javascript:alert(1)"
    artifact.canonical_url = "https://example.test/safe"
    artifact.url = "https://example.test/legacy"
    artifact.published_at = None

    result = _clarity_for_artifact(artifact)

    assert result["traceable_claims"][0]["source"]["url"] == (
        "https://example.test/safe"
    )


def test_claim_traceability_uses_verified_passages_for_paraphrased_claims() -> None:
    """A paraphrased claim should keep its text and show the source wording."""

    artifact = MagicMock()
    artifact.raw_text = "Revenue totalled $112 million, compared with $100 million last year."
    artifact.artifact_metadata = {
        "confirmed_facts": ["Revenue increased by 12%."],
        "speculation": [],
        "claim_evidence": [
            {
                "text": "Revenue increased by 12%.",
                "kind": "confirmed_fact",
                "passage": artifact.raw_text,
            },
        ],
    }
    artifact.source_type = "asx_announcement"
    artifact.title = "Results update"
    artifact.document_url = "https://example.test/results.pdf"
    artifact.published_at = None

    claim = _clarity_for_artifact(artifact)["traceable_claims"][0]

    assert claim["text"] == "Revenue increased by 12%."
    assert claim["source"]["evidence_text"] == artifact.raw_text
    artifact.raw_text = "The document was replaced with an unrelated update."
    stale_claim = _clarity_for_artifact(artifact)["traceable_claims"][0]
    assert stale_claim["source"]["evidence_text"] is None




def test_claim_traceability_rejects_malformed_document_urls():
    assert safe_source_url("https://[invalid-host/results.pdf") is None
