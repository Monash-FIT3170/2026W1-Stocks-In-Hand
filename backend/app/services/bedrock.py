"""Bounded Amazon Bedrock text-generation adapter."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings


LOGGER = logging.getLogger(__name__)
_REASONING_PREFIX = re.compile(r"^<reasoning>.*?</reasoning>\s*", re.DOTALL)


@lru_cache(maxsize=4)
def _client(region_name: str) -> Any:
    return boto3.client(
        "bedrock-runtime",
        region_name=region_name,
        config=Config(
            connect_timeout=5,
            read_timeout=90,
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )


def _response_body(response: dict[str, Any]) -> dict[str, Any]:
    body = response.get("body")
    if body is None:
        raise ValueError("Bedrock response did not include a body")
    raw = body.read() if hasattr(body, "read") else body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Bedrock response body was not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Bedrock response body must be a JSON object")
    return data


def _message_text(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Bedrock response did not include text output") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Bedrock response text output was empty")

    cleaned = content.strip()
    if cleaned.startswith("<reasoning>") and "</reasoning>" not in cleaned:
        raise ValueError("Bedrock response contained incomplete reasoning output")
    cleaned = _REASONING_PREFIX.sub("", cleaned).strip()
    if not cleaned:
        raise ValueError("Bedrock response did not include an answer after reasoning")
    return cleaned


def invoke_text(prompt: str, *, temperature: float = 0.2) -> str:
    """Invoke the configured Bedrock model without logging prompt content."""
    if not settings.BEDROCK_ENABLED:
        raise RuntimeError("Amazon Bedrock is disabled")
    if not prompt.strip():
        raise ValueError("Bedrock prompt must not be empty")
    if len(prompt) > settings.BEDROCK_MAX_PROMPT_CHARS:
        raise ValueError(
            "Bedrock prompt exceeds the configured character limit "
            f"of {settings.BEDROCK_MAX_PROMPT_CHARS}"
        )

    payload = {
        "model": settings.BEDROCK_MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": settings.BEDROCK_MAX_OUTPUT_TOKENS,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "service_tier": settings.BEDROCK_SERVICE_TIER,
        "stream": False,
    }
    try:
        response = _client(settings.AWS_REGION).invoke_model(
            modelId=settings.BEDROCK_MODEL_ID,
            body=json.dumps(payload),
            accept="application/json",
            contentType="application/json",
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("Amazon Bedrock model invocation failed") from exc

    data = _response_body(response)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    LOGGER.info(
        "Bedrock invocation completed model=%s tier=%s input_tokens=%s output_tokens=%s",
        settings.BEDROCK_MODEL_ID,
        settings.BEDROCK_SERVICE_TIER,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )
    return _message_text(data)
