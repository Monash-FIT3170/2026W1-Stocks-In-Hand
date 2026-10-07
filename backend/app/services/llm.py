"""Summaries and category splits from the configured LLM, as plain values.

Each function generates one kind through ``app.services.generation`` and
raises ``LLMUnavailableError`` when no provider is switched on.
"""

from __future__ import annotations

from typing import TypeVar

from app.services import generation
from app.services.generation import (
    CATEGORY_KEYS,
    SUMMARY_LIST_KEYS,
    SUMMARY_TEXT_KEYS,
    AnnouncementSummary,
    CategorySplit,
    DiscussionSummary,
    NewsSummary,
    RedditDigest,
    providers,
)
from app.services.generation.kinds import Kind
from app.services.llm_errors import LLMUnavailableError

T = TypeVar("T")

PROMPT_VERSION = CategorySplit.prompt_version
NEWS_SUMMARY_PROMPT_VERSION = NewsSummary.prompt_version
PUBLIC_DISCUSSION_SUMMARY_PROMPT_VERSION = DiscussionSummary.prompt_version
SUMMARY_PROMPT_VERSION = AnnouncementSummary.prompt_version
REDDIT_DIGEST_PROMPT_VERSION = RedditDigest.prompt_version

__all__ = (
    "CATEGORY_KEYS",
    "NEWS_SUMMARY_PROMPT_VERSION",
    "PROMPT_VERSION",
    "PUBLIC_DISCUSSION_SUMMARY_PROMPT_VERSION",
    "REDDIT_DIGEST_PROMPT_VERSION",
    "SUMMARY_LIST_KEYS",
    "SUMMARY_PROMPT_VERSION",
    "SUMMARY_TEXT_KEYS",
    "active_model_name",
    "categorise_chunk",
    "categorise_chunk_in_batches",
    "summarise_announcement",
    "summarise_news_article",
    "summarise_public_discussion",
    "summarise_reddit_digest",
)


def active_model_name() -> str:
    """Return the configured provider and model for stored provenance."""
    return providers.configured_provider().name


def _value(kind: Kind[T]) -> T:
    result = generation.generate(kind)
    if isinstance(result, generation.Unavailable):
        raise LLMUnavailableError(result.reason)
    return result.value


def categorise_chunk(chunk: str) -> dict[str, str]:
    """Sort announcement evidence into the supported categories."""
    return _value(CategorySplit(chunk))


def categorise_chunk_in_batches(chunk: str, batch_size: int) -> dict[str, str]:
    """Categorise a large artifact chunk in bounded batches."""
    return _value(CategorySplit(chunk, batch_size=batch_size))


def summarise_announcement(
    *,
    title: str,
    category: str,
    extracted_data: dict,
    raw_text: str,
) -> dict[str, object]:
    """Summarise an official ASX announcement."""
    return _value(
        AnnouncementSummary(
            title=title,
            category=category,
            extracted_data=extracted_data,
            raw_text=raw_text,
        )
    )


def summarise_news_article(
    *,
    title: str,
    source_name: str | None,
    raw_text: str,
) -> dict[str, object]:
    """Summarise a financial news article."""
    return _value(NewsSummary(title=title, source_name=source_name, raw_text=raw_text))


def summarise_public_discussion(
    *,
    title: str,
    source_type: str,
    raw_text: str,
) -> dict[str, object]:
    """Summarise one public discussion post."""
    return _value(
        DiscussionSummary(title=title, source_type=source_type, raw_text=raw_text)
    )


def summarise_reddit_digest(
    *,
    ticker_symbol: str,
    posts: list[dict],
    source_name: str = "Reddit",
) -> dict[str, object]:
    """Summarise a bounded group of Reddit posts."""
    return _value(
        RedditDigest(ticker_symbol=ticker_symbol, posts=posts, source_name=source_name)
    )
