"""Groq's rejected JSON must reach bounded repair and quotation validation."""

import json
from unittest.mock import patch

import httpx
import pytest

from app.services import llm


def response(status, data):
    return httpx.Response(status, json=data, request=httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions'))


def summary():
    return {
        'summary': 'Revenue increased.', 'about': 'The company reports results.',
        'changed': 'Revenue rose 12%.', 'matters': 'Growth may continue.',
        'confirmed_facts': ['Revenue rose 12%.'], 'speculation': [],
        'claim_evidence': [
            {'field': 'confirmed_facts', 'index': 0, 'quote': 'Revenue increased by 12%.'},
            {'field': 'changed', 'index': 0, 'quote': 'Revenue increased by 99%.'},
        ],
    }


def test_rejected_groq_json_is_repaired_before_quote_validation():
    malformed = '{"summary": "Revenue increased."'
    repaired = json.dumps(summary())
    rejected = response(400, {'error': {'code': 'json_validate_failed', 'failed_generation': malformed}})
    malformed_text = response(200, {'choices': [{'message': {'content': malformed}}]})
    accepted = response(200, {'choices': [{'message': {'content': repaired}}]})
    with patch.object(llm.settings, 'LLM_PROVIDER', 'groq'), patch.object(llm.settings, 'GROQ_API_KEY', 'test-key'), patch.object(llm.httpx, 'post', side_effect=[rejected, malformed_text, accepted]) as invoke:
        result = llm.summarise_announcement(title='Results', category='results', extracted_data={}, raw_text='Revenue increased by 12%.')
    assert invoke.call_count == 3
    assert "response_format" not in invoke.call_args_list[1].kwargs["json"]
    assert json.dumps(malformed) in invoke.call_args_list[2].kwargs['json']['messages'][0]['content']
    assert invoke.call_args_list[2].kwargs['json']['temperature'] == 0
    assert len(result['claim_evidence']) == 1
    assert result['claim_evidence'][0]['quote'] == 'Revenue increased by 12%.'


def test_recovery_remains_bounded_when_repair_is_also_rejected():
    rejected = response(400, {'error': {'code': 'json_validate_failed', 'failed_generation': '{"summary":'}})
    with patch.object(llm.settings, 'LLM_PROVIDER', 'groq'), patch.object(llm.settings, 'GROQ_API_KEY', 'test-key'), patch.object(llm.httpx, 'post', return_value=rejected) as invoke, pytest.raises(ValueError):
        llm.summarise_announcement(title='Results', category='results', extracted_data={}, raw_text='Revenue increased by 12%.')
    assert invoke.call_count == 2 * (1 + llm.SUMMARY_REPAIR_ATTEMPTS)


@pytest.mark.parametrize(('status', 'error'), [
    (401, {'code': 'json_validate_failed', 'failed_generation': 'private document text'}),
    (400, {'code': 'invalid_api_key', 'failed_generation': 'private document text'}),
    (400, {'code': 'json_validate_failed'}),
    (400, {'code': 'json_validate_failed', 'failed_generation': ''}),
    (400, {'code': 'json_validate_failed', 'failed_generation': {'unexpected': 'object'}}),
])
def test_other_errors_are_not_returned_as_model_output(status, error):
    rejected = response(status, {'error': {**error, 'message': 'private provider details'}})
    with patch.object(llm.settings, 'GROQ_API_KEY', 'test-key'), patch.object(llm.httpx, 'post', return_value=rejected), pytest.raises(RuntimeError) as caught:
        llm._call_groq('Synthetic test')
    assert str(caught.value) == f'Groq model invocation failed (HTTP {status})'
    assert 'private' not in str(caught.value)


def test_malformed_http_error_body_is_safely_rejected():
    rejected = httpx.Response(400, text='not JSON', request=httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions'))
    assert llm._groq_failed_generation(rejected) is None


@pytest.mark.parametrize("generated", [None, "", {"unexpected": "object"}])
def test_missing_rejected_output_retries_without_json_mode_once(generated):
    error = {"code": "json_validate_failed"}
    if generated is not None:
        error["failed_generation"] = generated
    rejected = response(400, {"error": error})
    accepted = response(200, {"choices": [{"message": {"content": json.dumps(summary())}}]})
    with patch.object(llm.settings, "LLM_PROVIDER", "groq"), patch.object(llm.settings, "GROQ_API_KEY", "test-key"), patch.object(llm.httpx, "post", side_effect=[rejected, accepted]) as invoke:
        result = llm.summarise_announcement(title="Results", category="results", extracted_data={}, raw_text="Revenue increased by 12%.")
    assert invoke.call_count == 2
    first, second = [call.kwargs["json"] for call in invoke.call_args_list]
    assert first["response_format"]["type"] == "json_schema"
    assert first["response_format"]["json_schema"]["strict"] is True
    assert "response_format" not in second
    assert first["messages"] == second["messages"]
    assert len(result["claim_evidence"]) == 1
    assert result["claim_evidence"][0]["quote"] == "Revenue increased by 12%."


def test_plain_text_fallback_keeps_schema_validation_and_bounded_repair():
    rejected = response(400, {"error": {"code": "json_validate_failed"}})
    unstructured = response(200, {"choices": [{"message": {"content": "not a summary JSON object"}}]})
    with patch.object(llm.settings, "LLM_PROVIDER", "groq"), patch.object(llm.settings, "GROQ_API_KEY", "test-key"), patch.object(llm.httpx, "post", side_effect=[rejected, unstructured, unstructured, unstructured]) as invoke, pytest.raises(ValueError):
        llm.summarise_announcement(title="Results", category="results", extracted_data={}, raw_text="Revenue increased by 12%.")
    assert invoke.call_count == 2 + llm.SUMMARY_REPAIR_ATTEMPTS


@pytest.mark.parametrize('value', ['', '   ', None, 42, {}])
def test_summary_parser_rejects_empty_or_non_text_display_fields(value):
    data = summary()
    data['summary'] = value
    with pytest.raises(ValueError, match='summary.*non-empty string'):
        llm.parse_summary_response(json.dumps(data))


def test_empty_summary_repair_uses_original_source_and_preserves_quotes():
    empty = {**{key: '' for key in llm.SUMMARY_TEXT_KEYS}, 'confirmed_facts': [], 'speculation': []}
    source = 'Revenue increased by 12%.'
    with patch.object(llm, '_call_llm', side_effect=[json.dumps(empty), json.dumps(summary())]) as invoke:
        result = llm.summarise_announcement(title='Results', category='results', extracted_data={}, raw_text=source)
    repair_prompt = invoke.call_args_list[1].args[0]
    assert source in repair_prompt
    assert 'Never return an empty summary object' in repair_prompt
    assert all(result[key].strip() for key in llm.SUMMARY_TEXT_KEYS)
    assert len(result['claim_evidence']) == 1


def test_unrecoverable_empty_summary_fails_instead_of_becoming_success():
    empty = json.dumps({**{key: '' for key in llm.SUMMARY_TEXT_KEYS}, 'confirmed_facts': [], 'speculation': []})
    with patch.object(llm, '_call_llm', return_value=empty) as invoke, pytest.raises(ValueError, match='non-empty string'):
        llm.summarise_announcement(title='Results', category='results', extracted_data={}, raw_text='Revenue increased by 12%.')
    assert invoke.call_count == 1 + llm.SUMMARY_REPAIR_ATTEMPTS


def test_source_aware_repair_prompt_stays_bounded_even_with_json_escaping():
    prompt = llm._build_summary_repair_prompt('\\\n"' * 20000, include_clarity=True, source_prompt='Source: \\ \n"' * 20000)
    assert len(prompt) < 30000
    assert 'original summarisation request' in prompt


@pytest.mark.parametrize("include_clarity", [True, False])
def test_supported_groq_models_request_typed_required_quotation_records(include_clarity):
    accepted = response(200, {"choices": [{"message": {"content": json.dumps(summary())}}]})
    with patch.object(llm.settings, "LLM_PROVIDER", "groq"), patch.object(llm.settings, "GROQ_MODEL", "openai/gpt-oss-20b"), patch.object(llm.settings, "GROQ_API_KEY", "test-key"), patch.object(llm.httpx, "post", return_value=accepted) as invoke:
        llm._call_llm("Synthetic input", summary_clarity=include_clarity)
    payload = invoke.call_args.kwargs["json"]
    assert payload["temperature"] == 0
    assert payload["reasoning_effort"] == "low"
    assert payload["include_reasoning"] is False
    assert payload["max_completion_tokens"] == 4096
    contract = payload["response_format"]["json_schema"]
    assert contract["strict"] is True
    schema = contract["schema"]
    assert schema["additionalProperties"] is False
    assert "claim_evidence" in schema["required"]
    evidence = schema["properties"]["claim_evidence"]["items"]
    assert evidence["required"] == ["field", "index", "quote", "passage_id"]
    assert evidence["additionalProperties"] is False
    assert ("confirmed_facts" in schema["properties"]) is include_clarity
    assert ("confirmed_facts" in evidence["properties"]["field"]["enum"]) is include_clarity


def test_other_groq_models_retain_json_object_compatibility():
    accepted = response(200, {"choices": [{"message": {"content": json.dumps(summary())}}]})
    with patch.object(llm.settings, "LLM_PROVIDER", "groq"), patch.object(llm.settings, "GROQ_MODEL", "custom-model"), patch.object(llm.settings, "GROQ_API_KEY", "test-key"), patch.object(llm.httpx, "post", return_value=accepted) as invoke:
        llm._call_llm("Synthetic input", summary_clarity=True)
    assert invoke.call_args.kwargs["json"]["response_format"] == {"type": "json_object"}


def test_model_passage_enum_is_limited_to_supplied_source_ids():
    accepted = response(200, {"choices": [{"message": {"content": json.dumps(summary())}}]})
    with patch.object(llm.settings, "LLM_PROVIDER", "groq"), patch.object(llm.settings, "GROQ_MODEL", "openai/gpt-oss-20b"), patch.object(llm.settings, "GROQ_API_KEY", "test-key"), patch.object(llm.httpx, "post", return_value=accepted) as invoke:
        llm._call_llm("Synthetic input", summary_clarity=True, summary_passage_ids=["S001", "S002"])
    evidence = invoke.call_args.kwargs["json"]["response_format"]["json_schema"]["schema"]["properties"]["claim_evidence"]["items"]
    assert evidence["properties"]["passage_id"]["enum"] == ["", "S001", "S002"]
