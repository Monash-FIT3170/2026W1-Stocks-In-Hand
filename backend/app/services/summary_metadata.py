"""Shared helpers for preserving and reading structured LLM summaries."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


SUMMARY_TEXT_KEYS = ("summary", "about", "changed", "matters")
SUMMARY_LIST_KEYS = ("confirmed_facts", "speculation")
_SECTION_BREAK = re.compile(r"\r?\n\r?\n")


def normalise_summary_metadata(summary: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return only validated structured summary fields."""
    if not isinstance(summary, Mapping):
        return {}

    result: dict[str, Any] = {}
    for key in SUMMARY_TEXT_KEYS:
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    for key in SUMMARY_LIST_KEYS:
        value = summary.get(key)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            result[key] = [item.strip() for item in value if item.strip()]
    return result


def has_complete_summary_metadata(metadata: Mapping[str, Any] | None) -> bool:
    """Return whether all display and clarity fields have valid values."""
    if not isinstance(metadata, Mapping):
        return False
    return all(
        isinstance(metadata.get(key), str) and bool(metadata[key].strip())
        for key in SUMMARY_TEXT_KEYS
    ) and all(isinstance(metadata.get(key), list) for key in SUMMARY_LIST_KEYS)


def combine_summary_text(summary: Mapping[str, Any] | None) -> str:
    """Build the persisted human-readable summary from its four text fields."""
    fields = normalise_summary_metadata(summary)
    return "\n\n".join(
        str(fields[key]) for key in SUMMARY_TEXT_KEYS if key in fields
    )


def split_combined_summary_text(text: object) -> dict[str, str]:
    """Recover the four legacy text fields only when the split is lossless."""
    if not isinstance(text, str) or not text.strip():
        return {}
    parts = [part.strip() for part in _SECTION_BREAK.split(text.strip())]
    if len(parts) != len(SUMMARY_TEXT_KEYS) or any(not part for part in parts):
        return {}
    return dict(zip(SUMMARY_TEXT_KEYS, parts, strict=True))
