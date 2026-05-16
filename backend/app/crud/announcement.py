import re

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.artifact import Artifact
from app.schemas.announcement import AnnouncementResponse


_WHITESPACE = re.compile(r"\s+")
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _WHITESPACE.sub(" ", value).strip()
    return cleaned or None


def _preview_text(value: object, max_length: int = 220) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[:max_length].rstrip()}..."


def _metadata_value(metadata: dict | None, *keys: str) -> str | None:
    if not isinstance(metadata, dict):
        return None
    for key in keys:
        cleaned = _clean_text(metadata.get(key))
        if cleaned:
            return cleaned
    return None


def _format_label(value: object, fallback: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned or cleaned.upper() == "UNKNOWN":
        cleaned = fallback
    label = cleaned.replace("_", " ").replace("-", " ")
    label = _CAMEL_BOUNDARY.sub(" ", label)
    return label.title()


def _announcement_from_artifact(artifact: Artifact) -> AnnouncementResponse:
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    title = _clean_text(artifact.title) or "Untitled ASX announcement"

    return AnnouncementResponse(
        id=artifact.id,
        ticker=artifact.ticker.symbol if artifact.ticker else "ASX",
        tag=_format_label(metadata.get("category"), artifact.artifact_type),
        published_at=artifact.published_at or artifact.created_at,
        title=title,
        about=(
            _metadata_value(metadata, "about", "what_its_about", "what_it_is_about")
            or _preview_text(artifact.raw_text)
            or title
        ),
        changed=(
            _metadata_value(metadata, "changed", "what_changed")
            or "No change summary available yet."
        ),
        matters=(
            _metadata_value(metadata, "matters", "why_it_matters")
            or "No impact summary available yet."
        ),
        url=(
            _clean_text(artifact.url)
            or _metadata_value(metadata, "source_url", "pdf_url")
        ),
    )


def get_announcements(db: Session, limit: int = 50, offset: int = 0) -> list[AnnouncementResponse]:
    artifacts = (
        db.query(Artifact)
        .options(joinedload(Artifact.ticker))
        .filter(Artifact.source_type == "asx_announcement")
        .filter((Artifact.is_duplicate.is_(False)) | (Artifact.is_duplicate.is_(None)))
        .order_by(func.coalesce(Artifact.published_at, Artifact.created_at).desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_announcement_from_artifact(artifact) for artifact in artifacts]

