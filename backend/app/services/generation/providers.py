"""The text provider interface and the provider the deployment configures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import settings
from app.services.generation.bedrock import BedrockProvider
from app.services.generation.groq import GroqProvider


class TextProvider(Protocol):
    """One LLM that turns a prompt into its text answer.

    ``name`` is the provider and model, recorded with everything it generates.
    ``complete`` raises ``LLMUnavailableError`` when the provider is switched
    off or has no credentials, ``ValueError`` when it cannot accept the prompt
    or its answer has no text, and ``RuntimeError`` for a failure worth
    retrying.
    """

    @property
    def name(self) -> str: ...

    def complete(self, prompt: str, *, temperature: float) -> str: ...


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


@dataclass
class ScriptedProvider:
    """Answers with scripted responses in order and records every call.

    A scripted exception is raised instead of answered, so tests can script an
    unavailable provider or a failed call.
    """

    responses: list[str | Exception]
    name: str = "scripted:test-model"
    calls: list[ScriptedCall] = field(default_factory=list)

    def complete(self, prompt: str, *, temperature: float) -> str:
        self.calls.append(ScriptedCall(prompt, temperature))
        if not self.responses:
            raise AssertionError("ScriptedProvider has no response left")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
