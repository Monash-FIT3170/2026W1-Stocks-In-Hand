"""Reusable summarisation helpers for stored news artifacts."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.artifact_summary import ArtifactSummary
from app.services import gemini as summary_service

SUMMARY_METADATA_KEYS = ("summary", "about", "changed", "matters")


def summary_text(title: str, summary: dict[str, str]) -> str:
    parts = [summary.get(key) for key in SUMMARY_METADATA_KEYS]
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    return "\n\n".join(cleaned) or title


def has_news_summary_metadata(artifact: Artifact) -> bool:
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    about = metadata.get("about")
    return isinstance(about, str) and bool(about.strip())


def summarise_news_artifact(db: Session, artifact: Artifact) -> ArtifactSummary:
    raw_text = (artifact.raw_text or "").strip()
    if not raw_text:
        raise ValueError("News artifact has no text to summarise")

    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    source_name = metadata.get("source_name")
    source_name = source_name if isinstance(source_name, str) else None
    title = artifact.title or "Untitled news story"

    summary = summary_service.summarise_news_article(
        title=title,
        source_name=source_name,
        raw_text=raw_text,
    )

    next_metadata = dict(metadata)
    for key in SUMMARY_METADATA_KEYS:
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            next_metadata[key] = value
    artifact.artifact_metadata = next_metadata

    db_summary = ArtifactSummary(
        artifact_id=artifact.id,
        summary_text=summary_text(title, summary),
        model_used=summary_service.active_model_name(),
        prompt_version=summary_service.NEWS_SUMMARY_PROMPT_VERSION,
    )
    db.add(db_summary)
    db.commit()
    db.refresh(db_summary)
    return db_summary
