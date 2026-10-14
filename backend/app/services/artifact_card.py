"""Artifact card: how one artifact appears in a feed.

The market feed (``/announcements``) and a ticker's news feed show each
artifact as the same card: a tag, a title, where it came from with a link to
the original, and the about, changed and matters lines of its summary. A
line the summary does not have is None. A card never shows placeholder text
or the artifact's raw text in place of a summary. A ticker's brief and deep
dive show an artifact's tag and sources the same way.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.models.artifact import Artifact
from app.services import artifact_summary

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


@dataclass(frozen=True)
class ArtifactCard:
    tag: str
    title: str
    source_type: str
    source_name: str | None
    source_label: str
    url: str | None
    about: str | None
    changed: str | None
    matters: str | None

    def fields(self) -> dict[str, object]:
        """The card's fields, for a feed item to include."""
        return asdict(self)


def artifact_card(artifact: Artifact) -> ArtifactCard:
    """The card for one artifact. Reads its summary, so load lists ``WITH_SUMMARY``."""
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    source_type = _clean_text(artifact.source_type) or "market_update"
    source_name, source_label = _origin(artifact, source_type, metadata)
    summary = artifact_summary.read(artifact)
    return ArtifactCard(
        tag=tag(artifact),
        title=_clean_text(artifact.title) or f"Untitled {label(source_type, 'market update')}",
        source_type=source_type,
        source_name=source_name,
        source_label=source_label,
        url=_clean_text(artifact.url)
        or _clean_text(metadata.get("source_url"))
        or _clean_text(metadata.get("pdf_url")),
        about=artifact_summary.brief(summary),
        changed=_clean_text(summary.changed) if summary else None,
        matters=_clean_text(summary.matters) if summary else None,
    )


def tag(artifact: Artifact) -> str:
    """The display name of the artifact's category, else of its artifact type."""
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    return label(metadata.get("category"), artifact.artifact_type)


def sources(artifact: Artifact) -> list[dict[str, Any]]:
    """The artifact's original source, as evidence for a feed item or brief."""
    url = _clean_text(artifact.url)
    if not url:
        return []
    source_label = label(artifact.source_type, "Source")
    published_at = artifact.published_at or artifact.created_at
    return [
        {
            "label": source_label,
            "title": _clean_text(artifact.title) or source_label,
            "url": url,
            "published_at": published_at.isoformat() if published_at else None,
            "evidence_text": _preview(artifact.raw_text, 180),
        }
    ]


def label(value: object, fallback: object) -> str:
    """A stored name, such as a category or source type, as display words.

    ``UNKNOWN`` or no value gives the fallback's words.
    """
    cleaned = _clean_text(value)
    if not cleaned or cleaned.upper() == "UNKNOWN":
        cleaned = _clean_text(fallback) or "Announcement"
    words = cleaned.replace("_", " ").replace("-", " ")
    # Split CamelCase category names such as "DividendAnnouncement", but leave
    # all-caps words alone so acronyms do not come back as "U N K N O W N".
    words = " ".join(
        word if word.isupper() else _CAMEL_BOUNDARY.sub(" ", word)
        for word in words.split()
    )
    return words.title()


def _origin(
    artifact: Artifact,
    source_type: str,
    metadata: dict[str, Any],
) -> tuple[str | None, str]:
    """Who published the artifact, and the label of the link to its original."""
    if source_type == "asx_announcement":
        return "ASX", "View original ASX filing"
    platform_name = _clean_text(artifact.platform.name) if artifact.platform else None
    if source_type == "reddit":
        return platform_name or "Reddit", "View original Reddit post"
    name = (
        _clean_text(metadata.get("source_name"))
        or _clean_text(metadata.get("provider"))
        or platform_name
    )
    return name, f"View original at {name}" if name else "View original source"


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None


def _preview(value: object, max_length: int) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned or len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[:max_length].rstrip()}..."
