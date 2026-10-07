"""The text provider interface and the provider the deployment configures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import settings
from app.services.generation.bedrock import BedrockProvider
from app.services.generation.groq import GroqProvider
from app.services.llm_errors import PromptTooLargeError


class TextProvider(Protocol):
    """One LLM that turns a prompt into its text answer.

    ``name`` is the provider and model, recorded with everything it generates.
    ``complete`` raises ``LLMUnavailableError`` when the provider is switched
    off or has no credentials, ``PromptTooLargeError`` when the prompt is
    longer than it accepts, ``ValueError`` when its answer has no text, and
    ``RuntimeError`` for a failure worth retrying.
    """

    @property
    def name(self) -> str: ...

    def complete(self, prompt: str, *, temperature: float, max_output_tokens: int) -> str: ...


def configured_provider() -> TextProvider:
    """The provider ``LLM_PROVIDER`` selects, reading its settings on each call."""
    if settings.LLM_PROVIDER == "bedrock":
        return BedrockProvider()
    if settings.LLM_PROVIDER == "groq":
        return GroqProvider()
    raise RuntimeError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")


@dataclass(frozen=True)
class ScriptedCall:
    prompt: str
    temperature: float
    max_output_tokens: int


@dataclass
class ScriptedProvider:
    """Answers with scripted responses in order and records every call.

    A scripted exception is raised instead of answered, so tests can script an
    unavailable provider or a failed call. With ``max_prompt_chars`` set, a
    longer prompt is refused the way Bedrock refuses one.
    """

    responses: list[str | Exception]
    name: str = "scripted:test-model"
    max_prompt_chars: int | None = None
    calls: list[ScriptedCall] = field(default_factory=list)

    def complete(self, prompt: str, *, temperature: float, max_output_tokens: int) -> str:
        self.calls.append(ScriptedCall(prompt, temperature, max_output_tokens))
        if self.max_prompt_chars is not None and len(prompt) > self.max_prompt_chars:
            raise PromptTooLargeError(
                "Scripted prompt is too large",
                max_chars=self.max_prompt_chars,
            )
        if not self.responses:
            raise AssertionError("ScriptedProvider has no response left")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
