import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.schemas.announcement import AnnouncementResponse


_WHITESPACE = re.compile(r"\s+")
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")
_SYDNEY_TZ = ZoneInfo("Australia/Sydney")


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


def _sydney_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    local_now = now.astimezone(_SYDNEY_TZ) if now else datetime.now(_SYDNEY_TZ)
    start = datetime.combine(local_now.date(), time.min, tzinfo=_SYDNEY_TZ)
    return start, start + timedelta(days=1)


def _sydney_date_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=_SYDNEY_TZ)


def _sydney_date_end(value: date) -> datetime:
    return _sydney_date_start(value) + timedelta(days=1)


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


def get_announcements(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    today: bool = False,
    sector: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[AnnouncementResponse]:
    date_value = func.coalesce(Artifact.published_at, Artifact.created_at)
    query = (
        db.query(Artifact)
        .options(joinedload(Artifact.ticker))
        .filter(Artifact.source_type == "asx_announcement")
        .filter((Artifact.is_duplicate.is_(False)) | (Artifact.is_duplicate.is_(None)))
    )

    has_custom_range = start_date is not None or end_date is not None

    if has_custom_range:
        if start_date:
            query = query.filter(date_value >= _sydney_date_start(start_date))
        if end_date:
            query = query.filter(date_value < _sydney_date_end(end_date))
    elif today:
        start, end = _sydney_day_bounds()
        query = query.filter(date_value >= start).filter(date_value < end)

    if sector:
        query = query.join(Artifact.ticker).filter(Ticker.sector == sector)

    artifacts = query.order_by(date_value.desc()).offset(offset).limit(limit).all()
    return [_announcement_from_artifact(artifact) for artifact in artifacts]
