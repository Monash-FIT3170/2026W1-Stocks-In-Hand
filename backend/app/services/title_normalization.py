"""Shared headline normalisation for announcement and news providers."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse


MAX_TITLE_LENGTH = 160

_GENERIC_SLUGS = {
    "asx announcements",
    "financial results operational reviews",
    "investor hub",
    "market announcements",
    "news",
}

_LEADING_LABELS = re.compile(
    r"^(?:(?:exchange|media|news|asx) releases?\s+|"
    r"financial results and operational reviews\s+|"
    r"asx announcements?\s+)+",
    flags=re.IGNORECASE,
)


def _slug_title(url: str | None) -> str | None:
    if not url:
        return None
    slug = unquote(urlparse(url).path.rstrip("/").split("/")[-1])
    slug = re.sub(r"\.(?:html?|aspx?|pdf)$", "", slug, flags=re.IGNORECASE)
    title = " ".join(slug.replace("-", " ").replace("_", " ").split())
    if (
        not title
        or title.casefold() in _GENERIC_SLUGS
        or len(title) < 8
        or len(title.split()) < 2
        or not re.search(r"[A-Za-z]", title)
    ):
        return None
    return title


def _truncate_at_word(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    shortened = value[: max_length - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{shortened or value[: max_length - 1].rstrip()}…"


def normalise_title(
    raw_title: str,
    source_url: str | None = None,
    *,
    max_length: int = MAX_TITLE_LENGTH,
) -> str:
    """Return a compact display title for any supported company or provider."""
    cleaned = " ".join((raw_title or "").split())
    if not cleaned:
        return "Untitled"

    slug_title = _slug_title(source_url)
    if slug_title:
        match = re.search(re.escape(slug_title), cleaned, flags=re.IGNORECASE)
        if match:
            cleaned = cleaned[match.start():match.end()]
        elif len(cleaned) > max_length and len(slug_title) <= max_length:
            cleaned = slug_title[0].upper() + slug_title[1:]

    if len(cleaned) > max_length:
        without_labels = _LEADING_LABELS.sub("", cleaned).strip()
        if without_labels:
            cleaned = without_labels

    cleaned = re.sub(r"^Bhp\b", "BHP", cleaned)
    return _truncate_at_word(cleaned, max_length)
