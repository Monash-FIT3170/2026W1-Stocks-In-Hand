"""Select the configured announcement summary provider."""

from __future__ import annotations

import os
from typing import Any


def active_provider_name() -> str:
    return os.getenv("SUMMARY_PROVIDER", "groq").strip().lower()


def _provider():
    name = active_provider_name()
    if name == "groq":
        from app.services import groq

        return groq
    if name == "ollama":
        from app.services import ollama

        return ollama
    raise RuntimeError("SUMMARY_PROVIDER must be 'groq' or 'ollama'")


def active_model_name() -> str:
    return _provider().active_model_name()


def active_prompt_version() -> str:
    provider = _provider()
    function = getattr(provider, "active_prompt_version", None)
    if function is not None:
        return str(function())
    return str(provider.SUMMARY_PROMPT_VERSION)


def ensure_provider_available() -> None:
    function = getattr(_provider(), "ensure_model_available", None)
    if function is not None:
        function()


def summarise_announcement(
    *,
    title: str,
    category: str,
    extracted_data: dict,
    raw_text: str,
) -> dict[str, Any]:
    return _provider().summarise_announcement(
        title=title,
        category=category,
        extracted_data=extracted_data,
        raw_text=raw_text,
    )
