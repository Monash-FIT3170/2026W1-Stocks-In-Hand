"""Groq behind the text provider interface, for local development only."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from app.core.config import settings
from app.services.llm_errors import LLMUnavailableError, PromptTooLargeError

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_RETRY_PROMPT_CHARS = 6000
GROQ_ATTEMPTS = 5


class GroqProvider:
    """The configured Groq model, retried while Groq rate-limits the key."""

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._sleep = sleep

    @property
    def name(self) -> str:
        return f"groq:{settings.GROQ_MODEL}"

    def complete(self, prompt: str, *, temperature: float, max_output_tokens: int) -> str:
        if not settings.GROQ_API_KEY:
            raise LLMUnavailableError("GROQ_API_KEY is not configured")
        payload = {
            "model": settings.GROQ_MODEL,
            "temperature": temperature,
            "max_completion_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
        with httpx.Client(transport=self._transport, timeout=60) as client:
            return self._complete(client, payload, len(prompt))

    def _complete(self, client: httpx.Client, payload: dict, prompt_chars: int) -> str:
        for attempt in range(GROQ_ATTEMPTS):
            try:
                response = client.post(
                    GROQ_CHAT_URL,
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # Free-tier keys answer 413 when a request is over their
                # per-minute token allowance. GROQ_RETRY_PROMPT_CHARS fits it.
                if (
                    exc.response.status_code == 413
                    and prompt_chars > GROQ_RETRY_PROMPT_CHARS
                ):
                    raise PromptTooLargeError(
                        "Groq rejected the prompt as too large",
                        max_chars=GROQ_RETRY_PROMPT_CHARS,
                    ) from exc
                if exc.response.status_code != 429:
                    raise RuntimeError("Groq model invocation failed") from exc
                response = exc.response
            except httpx.RequestError as exc:
                raise RuntimeError("Groq model invocation failed") from exc
            if response.status_code == 429:
                wait = int(response.headers.get("retry-after", min(2**attempt * 5, 60)))
                self._sleep(wait)
                continue
            data = response.json()
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ValueError("Groq response did not include text output") from exc
        raise RuntimeError(f"Groq rate limit exceeded after {GROQ_ATTEMPTS} retries")
