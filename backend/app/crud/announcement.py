import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.models.artifact import Artifact
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.ticker import Ticker
from app.schemas.announcement import AnnouncementResponse, TrendingAnnouncementResponse
from app.services.summary_metadata import (
    SUMMARY_TEXT_KEYS,
    normalise_summary_metadata,
    split_combined_summary_text,
)


_WHITESPACE = re.compile(r"\s+")
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")
_SYDNEY_TZ = ZoneInfo("Australia/Sydney")
FEED_SOURCE_TYPES = ("asx_announcement", "news", "reddit")


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


def _ticker_symbol(artifact: Artifact) -> str:
    if artifact.ticker and artifact.ticker.symbol:
        return str(artifact.ticker.symbol)
    mentioned_symbols = sorted(
        {
            str(mention.ticker.symbol)
            for mention in artifact.ticker_mentions
            if mention.ticker and mention.ticker.symbol
        }
    )
    return mentioned_symbols[0] if mentioned_symbols else "ASX"


def _source_details(artifact: Artifact) -> tuple[str, str, str]:
    source_type = _clean_text(artifact.source_type) or "market_update"
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    platform_name = _clean_text(artifact.platform.name) if artifact.platform else None

    if source_type == "asx_announcement":
        return source_type, "ASX", "View original ASX filing"
    if source_type == "reddit":
        return source_type, platform_name or "Reddit", "View original Reddit post"

    source_name = _metadata_value(metadata, "source_name", "provider") or platform_name
    source_name = source_name or "Publisher"
    return source_type, source_name, f"View original at {source_name}"


def _summary_fields(artifact: Artifact, metadata: dict) -> dict[str, str]:
    """Read structured metadata, with a safe fallback for legacy combined rows."""
    fields = {
        key: value
        for key, value in normalise_summary_metadata(metadata).items()
        if key in SUMMARY_TEXT_KEYS
    }
    if all(key in fields for key in SUMMARY_TEXT_KEYS):
        return fields

    summaries = getattr(artifact, "summaries", None) or []
    if summaries:
        recovered = split_combined_summary_text(summaries[0].summary_text)
        for key, value in recovered.items():
            fields.setdefault(key, value)
    return fields


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
    summary_fields = _summary_fields(artifact, metadata)
    source_type, source_name, source_label = _source_details(artifact)
    title = _clean_text(artifact.title) or f"Untitled {_format_label(source_type, 'market update')}"

    return AnnouncementResponse(
        id=artifact.id,
        ticker=_ticker_symbol(artifact),
        tag=_format_label(metadata.get("category"), artifact.artifact_type),
        source_type=source_type,
        source_name=source_name,
        source_label=source_label,
        published_at=artifact.published_at or artifact.created_at,
        title=title,
        about=(
            _clean_text(summary_fields.get("about"))
            or _metadata_value(
                metadata,
                "about",
                "what_its_about",
                "what_it_is_about",
            )
            or _clean_text(summary_fields.get("summary"))
            or _metadata_value(metadata, "summary")
            or _preview_text(artifact.raw_text)
            or title
        ),
        changed=(
            _clean_text(summary_fields.get("changed"))
            or _metadata_value(metadata, "changed", "what_changed")
            or "No change summary available yet."
        ),
        matters=(
            _clean_text(summary_fields.get("matters"))
            or _metadata_value(metadata, "matters", "why_it_matters")
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
        .options(
            joinedload(Artifact.ticker),
            joinedload(Artifact.platform),
            joinedload(Artifact.summaries),
            joinedload(Artifact.ticker_mentions).joinedload(
                ArtifactTickerMention.ticker
            ),
        )
        .filter(Artifact.source_type.in_(FEED_SOURCE_TYPES))
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
        query = query.filter(
            or_(
                Artifact.ticker.has(Ticker.sector == sector),
                Artifact.ticker_mentions.any(
                    ArtifactTickerMention.ticker.has(Ticker.sector == sector)
                ),
            )
        )

    # UUID provides deterministic ordering when several records share the same
    # publication timestamp. Stable ordering reduces overlap between offset pages.
    artifacts = (
        query.order_by(date_value.desc(), Artifact.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_announcement_from_artifact(artifact) for artifact in artifacts]


def get_trending_announcements(
    db: Session,
    days: int = 7,
    limit: int = 4,
) -> list[TrendingAnnouncementResponse]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    capped_limit = max(min(limit, 20), 1)
    date_value = func.coalesce(Artifact.published_at, Artifact.created_at)
    direct_artifacts = (
        db.query(
            Artifact.ticker_id.label("ticker_id"),
            Artifact.id.label("artifact_id"),
        )
        .filter(Artifact.ticker_id.isnot(None))
        .filter(Artifact.source_type.in_(FEED_SOURCE_TYPES))
        .filter(date_value >= cutoff)
    )
    mentioned_artifacts = (
        db.query(
            ArtifactTickerMention.ticker_id.label("ticker_id"),
            ArtifactTickerMention.artifact_id.label("artifact_id"),
        )
        .join(Artifact, Artifact.id == ArtifactTickerMention.artifact_id)
        .filter(Artifact.source_type.in_(FEED_SOURCE_TYPES))
        .filter(date_value >= cutoff)
    )
    feed_artifacts = direct_artifacts.union_all(mentioned_artifacts).subquery()
    count_value = func.count(func.distinct(feed_artifacts.c.artifact_id))

    rows = (
        db.query(Ticker.symbol, count_value.label("count"))
        .join(feed_artifacts, feed_artifacts.c.ticker_id == Ticker.id)
        .group_by(Ticker.symbol)
        .order_by(count_value.desc(), Ticker.symbol.asc())
        .limit(capped_limit)
        .all()
    )

    return [
        TrendingAnnouncementResponse(symbol=symbol, count=count)
        for symbol, count in rows
    ]
