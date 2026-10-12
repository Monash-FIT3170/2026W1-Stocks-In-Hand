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
    accepted = response(200, {'choices': [{'message': {'content': repaired}}]})
    with patch.object(llm.settings, 'LLM_PROVIDER', 'groq'), patch.object(llm.settings, 'GROQ_API_KEY', 'test-key'), patch.object(llm.httpx, 'post', side_effect=[rejected, accepted]) as invoke:
        result = llm.summarise_announcement(title='Results', category='results', extracted_data={}, raw_text='Revenue increased by 12%.')
    assert invoke.call_count == 2
    assert json.dumps(malformed) in invoke.call_args_list[1].kwargs['json']['messages'][0]['content']
    assert invoke.call_args_list[1].kwargs['json']['temperature'] == 0
    assert len(result['claim_evidence']) == 1
    assert result['claim_evidence'][0]['quote'] == 'Revenue increased by 12%.'


def test_recovery_remains_bounded_when_repair_is_also_rejected():
    rejected = response(400, {'error': {'code': 'json_validate_failed', 'failed_generation': '{"summary":'}})
    with patch.object(llm.settings, 'LLM_PROVIDER', 'groq'), patch.object(llm.settings, 'GROQ_API_KEY', 'test-key'), patch.object(llm.httpx, 'post', return_value=rejected) as invoke, pytest.raises(ValueError):
        llm.summarise_announcement(title='Results', category='results', extracted_data={}, raw_text='Revenue increased by 12%.')
    assert invoke.call_count == 1 + llm.SUMMARY_REPAIR_ATTEMPTS


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
