"""Structured generation: validated LLM output from whichever provider is configured.

``generate(kind)`` is the one entry point. It returns ``Generated`` with the
validated value, the model and the prompt version, or ``Unavailable`` when no
provider is switched on. A malformed answer raises ``ValueError`` after any
repair the kind allows, and a failure worth retrying raises ``RuntimeError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.services.generation import providers
from app.services.generation.kinds import (
    CATEGORY_KEYS,
    SUMMARY_LIST_KEYS,
    SUMMARY_TEXT_KEYS,
    AnnouncementSummary,
    Budget,
    CategorySplit,
    DiscussionSummary,
    Kind,
    NewsSummary,
    RedditDigest,
)
from app.services.generation.providers import TextProvider
from app.services.llm_errors import LLMUnavailableError, PromptTooLargeError

__all__ = (
    "CATEGORY_KEYS",
    "SUMMARY_LIST_KEYS",
    "SUMMARY_TEXT_KEYS",
    "AnnouncementSummary",
    "Budget",
    "CategorySplit",
    "DiscussionSummary",
    "Generated",
    "NewsSummary",
    "RedditDigest",
    "Unavailable",
    "generate",
)

T = TypeVar("T")
REPAIR_ATTEMPTS = 2


@dataclass(frozen=True)
class Generated(Generic[T]):
    """A validated value and what produced it."""

    value: T
    model: str
    prompt_version: str


@dataclass(frozen=True)
class Unavailable:
    """No LLM is switched on, so nothing was generated."""

    reason: str


def generate(kind: Kind[T], *, provider: TextProvider | None = None) -> Generated[T] | Unavailable:
    """Generate and validate one kind of output."""
    provider = provider or providers.configured_provider()
    try:
        values = [_generate_part(part, provider) for part in kind.parts()]
    except LLMUnavailableError as exc:
        return Unavailable(str(exc))
    return Generated(
        value=kind.combine(values),
        model=provider.name,
        prompt_version=kind.prompt_version,
    )


def _generate_part(part: Kind[T], provider: TextProvider) -> T:
    answer = _complete(part, provider)
    repairs_left = REPAIR_ATTEMPTS
    while True:
        try:
            return part.parse(answer)
        except ValueError:
            repair = part.repair(answer)
            if repair is None or repairs_left == 0:
                raise
        repairs_left -= 1
        answer = _complete(repair, provider)


def _complete(kind: Kind, provider: TextProvider) -> str:
    """Ask once with the source text cut to budget, and once more if it must be shorter."""
    source_text = kind.source_text[: kind.budget.input_chars]
    prompt = kind.prompt(source_text)
    try:
        return _ask(provider, kind, prompt)
    except PromptTooLargeError as exc:
        refused = exc
    while len(prompt) > refused.max_chars:
        shorter = len(source_text) - (len(prompt) - refused.max_chars)
        if shorter <= 0:
            raise refused
        source_text = source_text[:shorter]
        prompt = kind.prompt(source_text)
    return _ask(provider, kind, prompt)


def _ask(provider: TextProvider, kind: Kind, prompt: str) -> str:
    return provider.complete(
        prompt,
        temperature=kind.temperature,
        max_output_tokens=kind.budget.output_tokens,
    )
