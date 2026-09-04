"""Compatibility exports for the former Gemini-named LLM service."""

from app.services.llm import (
    CATEGORY_KEYS,
    NEWS_SUMMARY_PROMPT_VERSION,
    PROMPT_VERSION,
    PUBLIC_DISCUSSION_SUMMARY_PROMPT_VERSION,
    REDDIT_DIGEST_PROMPT_VERSION,
    SUMMARY_LIST_KEYS,
    SUMMARY_PROMPT_VERSION,
    SUMMARY_TEXT_KEYS,
    active_model_name,
    categorise_chunk,
    categorise_chunk_in_batches,
    parse_category_response,
    parse_reddit_digest_response,
    parse_summary_response,
    summarise_announcement,
    summarise_news_article,
    summarise_public_discussion,
    summarise_reddit_digest,
    __all__ as _LLM_EXPORTS,
)

__all__ = _LLM_EXPORTS
