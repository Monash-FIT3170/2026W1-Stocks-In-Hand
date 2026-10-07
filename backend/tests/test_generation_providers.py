"""The Bedrock and Groq adapters behind the text provider interface.

Each adapter is tested at its own boundary: Bedrock with a fake runtime
client, Groq with an httpx mock transport.
"""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.generation import providers
from app.services.generation.bedrock import BedrockProvider
from app.services.generation.groq import GROQ_RETRY_PROMPT_CHARS, GroqProvider
from app.services.llm_errors import LLMUnavailableError, PromptTooLargeError


def _bedrock_response(content: str) -> dict[str, io.BytesIO]:
    return {
        "body": io.BytesIO(
            json.dumps(
                {
                    "choices": [{"message": {"content": content}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10},
                }
            ).encode("utf-8")
        )
    }


@pytest.fixture()
def bedrock_enabled():
    with patch.multiple(
        settings,
        BEDROCK_ENABLED=True,
        BEDROCK_MODEL_ID="openai.gpt-oss-120b-1:0",
        BEDROCK_SERVICE_TIER="flex",
        BEDROCK_MAX_PROMPT_CHARS=30000,
    ):
        yield


def test_bedrock_sends_a_bounded_request_and_drops_reasoning(bedrock_enabled) -> None:
    client = MagicMock()
    client.invoke_model.return_value = _bedrock_response(
        '<reasoning>internal analysis</reasoning>\n{"summary": "Bounded output"}'
    )

    result = BedrockProvider(client).complete(
        "Summarise this filing.",
        temperature=0.2,
        max_output_tokens=1024,
    )

    assert result == '{"summary": "Bounded output"}'
    request = client.invoke_model.call_args.kwargs
    assert request["modelId"] == "openai.gpt-oss-120b-1:0"
    assert request["accept"] == "application/json"
    assert request["contentType"] == "application/json"
    assert json.loads(request["body"]) == {
        "model": "openai.gpt-oss-120b-1:0",
        "messages": [{"role": "user", "content": "Summarise this filing."}],
        "max_completion_tokens": 1024,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "service_tier": "flex",
        "stream": False,
    }


def test_disabled_bedrock_is_unavailable_before_any_call() -> None:
    client = MagicMock()

    with patch.object(settings, "BEDROCK_ENABLED", False), pytest.raises(
        LLMUnavailableError,
        match="disabled",
    ):
        BedrockProvider(client).complete("Prompt", temperature=0.2, max_output_tokens=64)

    client.invoke_model.assert_not_called()


def test_bedrock_refuses_a_prompt_over_its_limit_before_any_call(bedrock_enabled) -> None:
    client = MagicMock()

    with patch.object(settings, "BEDROCK_MAX_PROMPT_CHARS", 10), pytest.raises(
        PromptTooLargeError,
        match="character limit",
    ) as error:
        BedrockProvider(client).complete("x" * 11, temperature=0.2, max_output_tokens=64)

    assert error.value.max_chars == 10
    client.invoke_model.assert_not_called()


def test_bedrock_keeps_aws_error_details_inside(bedrock_enabled) -> None:
    client = MagicMock()
    client.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "sensitive detail"}},
        "InvokeModel",
    )

    with pytest.raises(RuntimeError) as error:
        BedrockProvider(client).complete("Prompt", temperature=0.2, max_output_tokens=64)

    assert str(error.value) == "Amazon Bedrock model invocation failed"
    assert "sensitive detail" not in str(error.value)


def _groq_answer(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


class _GroqServer:
    """Answers Groq requests in order and records each request body."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return self.responses.pop(0)


@pytest.fixture()
def groq_key():
    with patch.multiple(settings, GROQ_API_KEY="test-key", GROQ_MODEL="openai/gpt-oss-120b"):
        yield


def test_groq_asks_for_a_shorter_prompt_when_the_payload_is_too_large(groq_key) -> None:
    server = _GroqServer(httpx.Response(413))

    with pytest.raises(PromptTooLargeError) as error:
        GroqProvider(httpx.MockTransport(server)).complete(
            "x" * (GROQ_RETRY_PROMPT_CHARS + 1000),
            temperature=0.2,
            max_output_tokens=64,
        )

    assert error.value.max_chars == GROQ_RETRY_PROMPT_CHARS
    assert len(server.bodies) == 1


def test_groq_does_not_retry_a_small_payload_rejection(groq_key) -> None:
    server = _GroqServer(httpx.Response(413))

    with pytest.raises(RuntimeError, match="Groq model invocation failed"):
        GroqProvider(httpx.MockTransport(server)).complete(
            "small",
            temperature=0.2,
            max_output_tokens=64,
        )

    assert len(server.bodies) == 1


def test_groq_waits_out_a_rate_limit(groq_key) -> None:
    server = _GroqServer(
        httpx.Response(429, headers={"retry-after": "7"}),
        _groq_answer('{"summary":"ok"}'),
    )
    waits: list[float] = []

    result = GroqProvider(httpx.MockTransport(server), sleep=waits.append).complete(
        "prompt",
        temperature=0,
        max_output_tokens=512,
    )

    assert result == '{"summary":"ok"}'
    assert waits == [7]
    assert server.bodies[0]["temperature"] == 0
    assert server.bodies[0]["max_completion_tokens"] == 512
    assert server.bodies[0]["model"] == "openai/gpt-oss-120b"


def test_groq_without_a_key_is_unavailable() -> None:
    server = _GroqServer()

    with patch.object(settings, "GROQ_API_KEY", ""), pytest.raises(LLMUnavailableError):
        GroqProvider(httpx.MockTransport(server)).complete(
            "prompt",
            temperature=0.2,
            max_output_tokens=64,
        )

    assert server.bodies == []


@pytest.mark.parametrize(
    ("provider", "expected_type", "expected_name"),
    [
        ("bedrock", BedrockProvider, "bedrock:openai.gpt-oss-120b-1:0"),
        ("groq", GroqProvider, "groq:openai/gpt-oss-120b"),
    ],
)
def test_llm_provider_setting_selects_the_adapter(
    provider: str,
    expected_type: type,
    expected_name: str,
) -> None:
    with patch.multiple(
        settings,
        LLM_PROVIDER=provider,
        BEDROCK_MODEL_ID="openai.gpt-oss-120b-1:0",
        GROQ_MODEL="openai/gpt-oss-120b",
    ):
        selected = providers.configured_provider()

        assert isinstance(selected, expected_type)
        assert selected.name == expected_name
