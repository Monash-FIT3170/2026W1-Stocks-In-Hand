from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.models.artifact import Artifact
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.ticker import Ticker
from app.schemas.announcement import AnnouncementResponse, TrendingAnnouncementResponse
from app.services.artifact_card import artifact_card
from app.status import AnalysisStatus


_SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def _feed_eligible_filter():
    """Official items and non-official items not explicitly rejected.

    A completed legacy record with no decision remains visible during the
    compatibility/backfill window. New pending records stay hidden until
    analysis gives them an explicit decision.
    """
    decision = Artifact.artifact_metadata["feed_eligible"].as_boolean()
    return or_(
        Artifact.source_type == "asx_announcement",
        and_(
            Artifact.source_type.in_(("news", "reddit")),
            or_(
                decision.is_(True),
                and_(
                    decision.is_(None),
                    Artifact.analysis_status == AnalysisStatus.COMPLETED,
                ),
            ),
        ),
    )


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


def _sydney_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    local_now = now.astimezone(_SYDNEY_TZ) if now else datetime.now(_SYDNEY_TZ)
    start = datetime.combine(local_now.date(), time.min, tzinfo=_SYDNEY_TZ)
    return start, start + timedelta(days=1)


def _sydney_date_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=_SYDNEY_TZ)


def _sydney_date_end(value: date) -> datetime:
    return _sydney_date_start(value) + timedelta(days=1)


def _announcement_from_artifact(artifact: Artifact) -> AnnouncementResponse:
    return AnnouncementResponse(
        id=artifact.id,
        ticker=_ticker_symbol(artifact),
        published_at=artifact.published_at or artifact.created_at,
        **artifact_card(artifact).fields(),
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
        .filter(_feed_eligible_filter())
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
        .filter(_feed_eligible_filter())
        .filter(date_value >= cutoff)
    )
    mentioned_artifacts = (
        db.query(
            ArtifactTickerMention.ticker_id.label("ticker_id"),
            ArtifactTickerMention.artifact_id.label("artifact_id"),
        )
        .join(Artifact, Artifact.id == ArtifactTickerMention.artifact_id)
        .filter(_feed_eligible_filter())
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
