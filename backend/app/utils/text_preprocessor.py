"""Text preprocessing utilities for the summarisation pipeline."""

import re
import unicodedata
from html.parser import HTMLParser

DEFAULT_MAX_CHARS: int = 4000

_BOILERPLATE_PATTERNS: list[str] = [
    r"(subscribe|sign[\s-]?up)\s+(to|for)\s+.{0,60}(newsletter|alerts?|updates?)",
    r"click\s+here\s+to\s+(read|view|see|download)",
    r"(read|view)\s+more\s+(at|on|in)\s+",
    r"all\s+rights?\s+reserved",
    r"copyright\s+©?\s*\d{4}",
    r"terms?\s+(of\s+)?(use|service)\s*[|&]",
    r"privacy\s+policy",
    r"cookie\s+(policy|settings?|preferences?)",
    r"(this\s+)?article\s+(was\s+)?originally\s+published",
    r"advertisement",
    r"sponsored\s+content",
]

_BOILERPLATE_RE = re.compile(
    "|".join(_BOILERPLATE_PATTERNS),
    flags=re.IGNORECASE,
)


class _HTMLStripper(HTMLParser):

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(text: str) -> str:
    if not text:
        return ""
    stripper = _HTMLStripper()
    stripper.feed(text)
    return stripper.get_text()

def _normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    replacements = {
        "\u2018": "'",   # left single quotation mark
        "\u2019": "'",   # right single quotation mark
        "\u201c": '"',   # left double quotation mark
        "\u201d": '"',   # right double quotation mark
        "\u2013": "-",   # en dash
        "\u2014": "-",   # em dash
        "\u2026": "...", # horizontal ellipsis
        "\u00a0": " ",   # non-breaking space
        "\u200b": "",    # zero-width space
        "\u200c": "",    # zero-width non-joiner
        "\u200d": "",    # zero-width joiner
        "\ufeff": "",    # byte order mark
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text

def _remove_boilerplate(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+|\n", text)
    cleaned = [s for s in sentences if not _BOILERPLATE_RE.search(s)]
    return " ".join(cleaned)

def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def _remove_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "", text)

def _remove_repeated_punctuation(text: str) -> str:
    text = re.sub(r"\.{2,}", "...", text)
    text = re.sub(r"-{2,}", "-", text)
    text = re.sub(r"\*{2,}", "", text)
    text = re.sub(r"_{2,}", "", text)
    return text

def clean_text(text: str, *, strip_html_tags: bool = True) -> str:
    if not text:
        return ""

    if strip_html_tags:
        text = strip_html(text)

    text = _normalize_unicode(text)
    text = _remove_urls(text)
    text = _remove_boilerplate(text)
    text = _remove_repeated_punctuation(text)
    text = _normalize_whitespace(text)

    return text

def truncate_text(text: str, max_chars: int = DEFAULT_MAX_CHARS, *, truncation_marker: str = "...",) -> str:
    if not text:
        return ""

    if len(text) <= max_chars:
        return text

    cutoff = max_chars - len(truncation_marker)
    if cutoff <= 0:
        return truncation_marker[:max_chars]

    truncated = text[:cutoff]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]

    return truncated + truncation_marker

def preprocess(text: str, max_chars: int = DEFAULT_MAX_CHARS, *, strip_html_tags: bool = True,) -> str:
    cleaned = clean_text(text, strip_html_tags=strip_html_tags)
    return truncate_text(cleaned, max_chars=max_chars)
