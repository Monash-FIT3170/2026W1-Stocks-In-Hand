"""Tests for the bounded local Groq fallback."""

from unittest.mock import patch

import httpx
import pytest

from app.services import llm


def _response(status_code: int, *, content: str | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    if content is None:
        return httpx.Response(status_code, request=request)
    return httpx.Response(
        status_code,
        request=request,
        json={"choices": [{"message": {"content": content}}]},
    )


def test_groq_retries_payload_too_large_with_bounded_prompt() -> None:
    oversized_prompt = "x" * (llm.GROQ_RETRY_PROMPT_CHARS + 1000)

    with patch.object(llm.settings, "GROQ_API_KEY", "test-key"), patch.object(
        llm.httpx,
        "post",
        side_effect=[_response(413), _response(200, content='{"summary":"ok"}')],
    ) as post:
        result = llm._call_groq(oversized_prompt)

    assert result == '{"summary":"ok"}'
    assert post.call_count == 2
    first_payload = post.call_args_list[0].kwargs["json"]
    second_payload = post.call_args_list[1].kwargs["json"]
    assert len(first_payload["messages"][0]["content"]) == len(oversized_prompt)
    assert len(second_payload["messages"][0]["content"]) == llm.GROQ_RETRY_PROMPT_CHARS


def test_groq_does_not_retry_small_payload_rejection() -> None:
    with patch.object(llm.settings, "GROQ_API_KEY", "test-key"), patch.object(
        llm.httpx,
        "post",
        return_value=_response(413),
    ) as post, pytest.raises(RuntimeError, match="Groq model invocation failed"):
        llm._call_groq("small prompt")

    post.assert_called_once()
