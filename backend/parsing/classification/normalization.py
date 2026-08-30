"""Private bounded normalization and evidence matching helpers."""

from __future__ import annotations

import re
import unicodedata


_SEPARATOR = r"[\s\-_‐-―]+"


def safe_text(value: object, *, limit: int | None = None) -> str:
    """Convert malformed values safely and normalize Unicode without I/O."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = unicodedata.normalize("NFKC", text).replace("\x00", " ")
    return text[:limit] if limit is not None else text


def find_phrase(
    source: str,
    phrase: str,
    *,
    token: bool = False,
    regex: bool = False,
) -> str | None:
    """Return the original matched text for a case-insensitive rule."""
    normalized_phrase = safe_text(phrase).strip()
    if not normalized_phrase:
        return None
    if regex:
        expression = normalized_phrase
    elif token:
        expression = re.escape(normalized_phrase)
    else:
        expression = _SEPARATOR.join(
            re.escape(part) for part in normalized_phrase.split()
        )
    match = re.search(
        expression
        if regex
        else rf"(?<![A-Za-z0-9]){expression}(?![A-Za-z0-9])",
        source,
        flags=re.IGNORECASE,
    )
    return match.group(0) if match else None
