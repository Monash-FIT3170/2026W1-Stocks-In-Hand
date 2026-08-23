"""Local Ollama summary and sentiment provider.

The provider only accepts loopback endpoints. This keeps scraped financial
documents on the local machine when local analysis is selected.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SUMMARY_PROMPT_VERSION = "ollama-announcement-summary-v2"
_SUMMARY_KEYS = ("summary", "about", "changed", "matters")
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "host.docker.internal"}
_SENTIMENT_LABELS = {"positive", "neutral", "negative"}

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "about": {"type": "string"},
        "changed": {"type": "string"},
        "matters": {"type": "string"},
        "sentiment_label": {
            "type": "string",
            "enum": sorted(_SENTIMENT_LABELS),
        },
        "sentiment_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
    },
    "required": [
        *_SUMMARY_KEYS,
        "sentiment_label",
        "sentiment_confidence",
    ],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """You analyse official ASX company announcements.
Use only the supplied title, rule result, extracted fields, and document text.
Do not invent facts, prices, dates, causes, or investor advice.
Return short plain-English fields suitable for an investor news card.
The about field must state the filing's main purpose and match its title.
The changed field must state an explicit change, or say no material change stated.
The matters field must explain direct investor relevance without giving advice.
Classify document sentiment as positive, neutral, or negative.
Routine governance, compliance, filing, and administrative items are neutral
unless the document states a clear financial or operating impact.
Confidence must reflect direct evidence and should be lower when impact is unclear.
Return JSON matching the supplied schema and no other text."""


def _base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def _model_name() -> str:
    return os.getenv("OLLAMA_MODEL", "qwen3.5:latest").strip()


def _validated_base_url() -> str:
    value = _base_url()
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in _LOCAL_HOSTS:
        raise RuntimeError(
            "OLLAMA_BASE_URL must use HTTP on localhost, loopback, or "
            "host.docker.internal"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("OLLAMA_BASE_URL contains unsupported URL fields")
    if parsed.path not in {"", "/"}:
        raise RuntimeError("OLLAMA_BASE_URL must not contain a path")
    return value


def _request_json(path: str, payload: dict[str, Any] | None = None) -> dict:
    base_url = _validated_base_url()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    timeout = max(float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")), 1.0)
    try:
        # _validated_base_url restricts this request to local HTTP endpoints.
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"Ollama returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Ollama is unavailable at {base_url}") from exc
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise TypeError("Ollama returned an unexpected response")
    return value


def active_model_name() -> str:
    return f"ollama/{_model_name()}"


def active_prompt_version() -> str:
    return SUMMARY_PROMPT_VERSION


def ensure_model_available() -> None:
    model = _model_name()
    response = _request_json("/api/tags")
    installed = {
        str(item.get("name"))
        for item in response.get("models", [])
        if isinstance(item, dict)
    }
    if model not in installed:
        raise RuntimeError(
            f"Ollama model '{model}' is not installed. Installed: "
            + ", ".join(sorted(installed))
        )


def _clean_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Ollama field '{field}' is not text")
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        raise RuntimeError(f"Ollama field '{field}' is empty")
    return cleaned[:1200]


def _parse_content(content: object) -> dict[str, Any]:
    if not isinstance(content, str):
        raise TypeError("Ollama response did not contain message text")
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama message was not valid JSON") from exc
    if not isinstance(value, dict):
        raise TypeError("Ollama message was not a JSON object")

    result: dict[str, Any] = {
        key: _clean_text(value.get(key), field=key) for key in _SUMMARY_KEYS
    }
    sentiment = str(value.get("sentiment_label", "")).strip().lower()
    if sentiment not in _SENTIMENT_LABELS:
        raise RuntimeError("Ollama returned an invalid sentiment label")
    try:
        confidence = float(value.get("sentiment_confidence"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Ollama returned an invalid sentiment confidence") from exc
    if not 0 <= confidence <= 1:
        raise RuntimeError("Ollama sentiment confidence is outside 0 to 1")
    result["sentiment_label"] = sentiment
    result["sentiment_confidence"] = round(confidence, 4)
    return result


def summarise_announcement(
    *,
    title: str,
    category: str,
    extracted_data: dict,
    raw_text: str,
) -> dict[str, Any]:
    if not raw_text.strip():
        raise RuntimeError("Cannot summarise an announcement without document text")
    max_chars = max(int(os.getenv("MAX_ANALYSIS_CHARS", "50000")), 1000)
    user_prompt = (
        f"Title: {title}\n"
        f"Rule category: {category}\n"
        f"Extracted fields: {json.dumps(extracted_data, default=str)}\n\n"
        "Document text:\n"
        f"{raw_text[:max_chars]}"
    )
    response = _request_json(
        "/api/chat",
        {
            "model": _model_name(),
            "stream": False,
            "think": False,
            "format": _RESPONSE_SCHEMA,
            "options": {"temperature": 0.1, "num_predict": 700},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        },
    )
    message = response.get("message")
    if not isinstance(message, dict):
        raise TypeError("Ollama response did not contain a message")
    return _parse_content(message.get("content"))
