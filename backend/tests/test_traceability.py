"""Quotation fidelity and claim provenance regression tests."""

import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.services import llm
from app.services.summary_metadata import normalise_summary_metadata
from app.services.traceability import bind_claim_evidence, safe_source_url, trace_claims


def summary():
    return {
        "summary": "Revenue grew.", "about": "The company reports results.",
        "changed": "Revenue rose 12%.", "matters": "Growth may continue.",
        "confirmed_facts": ["Revenue rose 12%."],
        "speculation": ["Growth may continue."],
        "claim_evidence": [
            {"field": "confirmed_facts", "index": 0, "quote": "Revenue increased by 12%."},
            {"field": "speculation", "index": 0, "quote": "We expect further growth."},
        ],
    }


def artifact(metadata=None, raw_text="Revenue increased by 12%. We expect further growth.", **kwargs):
    return SimpleNamespace(
        id=uuid4(), title="Results", published_at=None, raw_text=raw_text,
        artifact_metadata=summary() if metadata is None else metadata,
        url="https://example.test/listing", document_url=kwargs.get("document_url", "https://example.test/report.pdf"),
    )


def test_quotes_use_exact_source_slice_with_pdf_line_wrapping():
    data = summary()
    raw = "Revenue increased\nby 12%. We expect further growth."
    evidence = bind_claim_evidence(data, raw)
    assert len(evidence) == 2
    assert evidence[0]["quote"] == "Revenue increased\nby 12%."
    for item in evidence:
        assert raw[item["start_char"]:item["end_char"]] == item["quote"]
        assert len(item["source_text_sha256"]) == 64
    assert normalise_summary_metadata({**data, "claim_evidence": evidence})["claim_evidence"] == evidence


@pytest.mark.parametrize("proposal", [
    {"field": "confirmed_facts", "index": 0, "quote": "Revenue increased by 99%."},
    {"field": "confirmed_facts", "index": 100, "quote": "Revenue increased by 12%."},
    {"field": "confirmed_facts", "index": True, "quote": "Revenue increased by 12%."},
    {"field": ["confirmed_facts"], "index": 0, "quote": "Revenue increased by 12%."},
    {"field": "unknown", "index": 0, "quote": "Revenue increased by 12%."},
    {"field": "confirmed_facts", "index": 0, "quote": "12%."},
    {"field": "confirmed_facts", "index": 0, "quote": ".* Revenue increased by 12%."},
    None,
])
def test_invalid_and_fabricated_proposals_are_discarded(proposal):
    assert bind_claim_evidence({**summary(), "claim_evidence": [proposal]}, "Revenue increased by 12%.") == []


def test_read_time_rejects_stale_claims_and_source_text():
    raw = "Revenue increased by 12%. We expect further growth."
    data = summary()
    data["claim_evidence"] = bind_claim_evidence(data, raw)
    data["confirmed_facts"] = ["Revenue rose 99%."]
    claims = trace_claims(artifact(data, raw))
    assert next(item for item in claims if item["field"] == "confirmed_facts")["status"] == "quotation_unavailable"
    assert all(item["evidence"] == [] for item in trace_claims(artifact(data, raw + " Updated.")))


def test_document_link_is_owned_by_artifact_and_claims_remain_separate():
    data = summary()
    data["claim_evidence"][0]["url"] = "https://malicious.test"
    claims = trace_claims(artifact(data))
    fact = next(item for item in claims if item["field"] == "confirmed_facts")
    forecast = next(item for item in claims if item["field"] == "speculation")
    assert fact["source"]["url"] == "https://example.test/report.pdf"
    assert fact["status"] == forecast["status"] == "quoted"
    assert fact["evidence"][0]["quote"] != forecast["evidence"][0]["quote"]
    assert "url" not in fact["evidence"][0]


def test_legacy_and_missing_source_states_are_explicit():
    data = summary()
    del data["claim_evidence"]
    assert all(item["status"] == "quotation_unavailable" for item in trace_claims(artifact(data)))
    item = artifact(document_url=None)
    item.url = None
    assert all(claim["status"] == "source_unavailable" for claim in trace_claims(item))
    assert trace_claims(None) == []


@pytest.mark.parametrize("url", ["javascript:alert(1)", "//example.test", "https://user:pass@example.test", "https://", "https://example.test\n", None])
def test_unsafe_links_are_not_exposed(url):
    assert safe_source_url(url) is None


def test_generation_checks_quotes_and_preserves_multiple_passages():
    data = summary()
    data["claim_evidence"].append(data["claim_evidence"][0].copy())
    data["claim_evidence"].append({"field": "about", "index": 0, "quote": "Invented source quotation."})
    with patch.object(llm, "_call_llm", return_value=json.dumps(data)) as invoke:
        result = llm.summarise_announcement(title="Results", category="results", extracted_data={}, raw_text="Revenue increased by 12%. We expect further growth.")
    assert len(result["claim_evidence"]) == 2
    assert "claim_evidence" in invoke.call_args.args[0]
    assert result["claim_evidence"][0]["claim_text"] == "Revenue rose 12%."


@pytest.mark.parametrize("generate,kwargs", [
    (llm.summarise_news_article, {"source_name": "Publisher"}),
    (llm.summarise_public_discussion, {"source_type": "reddit"}),
])
def test_linked_news_and_discussion_summaries_bind_evidence(generate, kwargs):
    data = {key: value for key, value in summary().items() if key not in {"confirmed_facts", "speculation"}}
    data["claim_evidence"] = [{"field": "changed", "index": 0, "quote": "Revenue increased by 12%."}]
    with patch.object(llm, "_call_llm", return_value=json.dumps(data)):
        result = generate(title="Update", raw_text="Revenue increased by 12%.", **kwargs)
    assert result["claim_evidence"][0]["claim_text"] == data["changed"]


def test_blank_claim_cleanup_does_not_move_quotation_to_a_different_claim():
    data = summary()
    data["confirmed_facts"] = ["", "Revenue rose 12%.", "Profit grew."]
    data["claim_evidence"] = [
        {"field": "confirmed_facts", "index": 0, "quote": "Revenue increased by 12%."},
        {"field": "confirmed_facts", "index": 1, "quote": "Revenue increased by 12%."},
    ]
    parsed = llm.parse_summary_response(json.dumps(data))
    evidence = bind_claim_evidence(parsed, "Revenue increased by 12%.")
    assert len(evidence) == 1
    assert evidence[0]["index"] == 0
    assert evidence[0]["claim_text"] == "Revenue rose 12%."


def test_numbered_table_passage_uses_stored_text_even_when_model_quote_is_empty():
    raw = "Name of Director Example Person\nDate of last notice 12 January 2026\nDate of change 7 October 2026\nNumber acquired\n\n5,000\n"
    data = {**summary(), "claim_evidence": [{"field": "confirmed_facts", "index": 0, "quote": "", "passage_id": "S001"}]}
    evidence = bind_claim_evidence(data, raw)
    assert evidence[0]['quote'] == raw
    assert evidence[0]['passage_id'] == 'S001'
    assert raw[evidence[0]['start_char']:evidence[0]['end_char']] == evidence[0]['quote']
    assert normalise_summary_metadata({**data, 'claim_evidence': evidence})['claim_evidence'] == evidence


def test_passage_references_cannot_fabricate_displayed_quotation():
    data = {**summary(), 'claim_evidence': [{'field': 'confirmed_facts', 'index': 0, 'quote': 'Revenue rose by 999%.', 'passage_id': 'S001'}]}
    raw = 'Revenue increased by 12%.'
    assert bind_claim_evidence(data, raw)[0]['quote'] == raw


@pytest.mark.parametrize('passage_id', ['S999', 'S1', 'https://malicious.test', 1, False, []])
def test_invalid_passage_reference_is_rejected_even_if_quote_matches(passage_id):
    data = {**summary(), 'claim_evidence': [{'field': 'confirmed_facts', 'index': 0, 'quote': 'Revenue increased by 12%.', 'passage_id': passage_id}]}
    assert bind_claim_evidence(data, 'Revenue increased by 12%.') == []


def test_passage_offsets_are_stable_and_bounded_to_the_model_source_window():
    from app.services.traceability import source_passages, SOURCE_WINDOW_CHARS
    raw = ('PDF label and value 15000\n' * 1000)
    passages = source_passages(raw)
    assert passages == source_passages(raw)
    previous_end = 0
    for passage in passages.values():
        assert passage['start_char'] == previous_end
        assert passage['end_char'] <= SOURCE_WINDOW_CHARS
        assert passage['end_char'] - passage['start_char'] <= 600
        assert raw[passage['start_char']:passage['end_char']] == passage['quote']
        previous_end = passage['end_char']


def test_cited_passage_does_not_survive_a_changed_source_snapshot():
    raw = 'Revenue increased by 12%.'
    data = {**summary(), 'claim_evidence': [{'field': 'confirmed_facts', 'index': 0, 'quote': '', 'passage_id': 'S001'}]}
    data['claim_evidence'] = bind_claim_evidence(data, raw)
    assert bind_claim_evidence(data, raw + ' Updated.') == []
