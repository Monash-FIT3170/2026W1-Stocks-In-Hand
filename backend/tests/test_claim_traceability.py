"""Regression tests for claim quotations and source validation."""

import json
from unittest.mock import patch

import pytest

from app.services import llm
from app.services.claim_traceability import exact_source_passage, validated_claim_evidence


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
    with patch.object(llm, "_call_llm", return_value=json.dumps(response)) as invoke:
        summary = llm.summarise_announcement(
            title="Results",
            category="revenue",
            extracted_data={},
            raw_text=passage,
        )

    assert summary["confirmed_facts"] == response["confirmed_facts"]
    assert summary["claim_evidence"] == response["claim_evidence"][:1]
    assert "verbatim supporting quotation" in invoke.call_args.args[0]
    assert validated_claim_evidence(summary, "An unrelated replacement document.") == []


def test_summary_parser_rejects_malformed_evidence_container() -> None:
    response = dict.fromkeys(llm.SUMMARY_TEXT_KEYS, "An update.")
    response.update(confirmed_facts=[], speculation=[], claim_evidence="not a list")
    with pytest.raises(ValueError, match="claim_evidence must be a list"):
        llm.parse_summary_response(json.dumps(response))
