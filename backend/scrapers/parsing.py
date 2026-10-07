"""Date and de-duplication helpers shared by the source adapters' parsers."""

from __future__ import annotations

import re
from collections.abc import Callable, Hashable, Iterable, Sequence
from datetime import datetime
from typing import TypeVar

Item = TypeVar("Item")

# Day-month-year dates as company sites print them.
DAY_MONTH_YEAR = r"\d{1,2}\s+[A-Za-z]+\s+\d{4}"  # 31 July 2026, 31 Jul 2026
MONTH_DAY_YEAR = r"[A-Za-z]+\s+\d{1,2},\s*\d{4}"  # July 31, 2026
SLASHED = r"\d{1,2}/\d{1,2}/\d{4}"  # 31/07/2026
DOTTED = r"\d{1,2}\.\d{1,2}\.\d{2}\b"  # 31.07.26
ISO = r"\d{4}-\d{2}-\d{2}"  # 2026-07-31


def unique(items: Iterable[Item], key: Callable[[Item], Hashable]) -> list[Item]:
    """The items in order, keeping the first of each key."""
    seen: set[Hashable] = set()
    kept: list[Item] = []
    for item in items:
        identity = key(item)
        if identity not in seen:
            seen.add(identity)
            kept.append(item)
    return kept


def parse_date(
    value: str,
    formats: Sequence[str],
    *,
    iso_fallback: bool = False,
) -> datetime | None:
    """The first of ``formats`` that reads the value, else None."""
    value = value.strip()
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    if iso_fallback:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def date_text(text: str, patterns: Sequence[str]) -> str | None:
    """The first date-shaped text, trying ``patterns`` in order, as whole words."""
    normalized = re.sub(r"\s+", " ", text)
    for pattern in patterns:
        match = re.search(rf"\b{pattern}\b", normalized)
        if match:
            return match.group(0)
    return None


def first_date(
    text: str,
    patterns: Sequence[str],
    formats: Sequence[str],
    *,
    iso_fallback: bool = False,
) -> datetime | None:
    """The first pattern's first match that parses, trying patterns in order."""
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            parsed = parse_date(match.group(0), formats, iso_fallback=iso_fallback)
            if parsed:
                return parsed
    return None
