"""Ticker topics: what a ticker's records have been about, and the developments under each topic.

Every content topic is listed, in taxonomy order, whether or not the ticker
has records about it, so the page can say a topic is quiet. Each topic says
how many distinct records discussed it in the last ``TREND_DAYS`` days and
in the ``TREND_DAYS`` before, and lists its topic clusters seen within the
window, newest first, each with its newest records and their evidence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, selectinload

from app.models.artifact import Artifact
from app.models.content_topic import (
    ArtifactContentTopic,
    ContentTopicCluster,
    ContentTopicClusterMember,
)
from app.read_models.ticker_records import find_ticker, record_date
from app.schemas.ticker_topics import (
    TickerTopic,
    TickerTopics,
    TopicClusterRecord,
    TopicClusterView,
    TopicTrend,
)
from app.services import artifact_card
from parsing.content_topics import TOPICS

DEFAULT_WINDOW_DAYS = 90
MAX_WINDOW_DAYS = 365
TREND_DAYS = 30
# The most clusters each topic shows, and records each cluster shows.
CLUSTERS_PER_TOPIC = 5
RECORDS_PER_CLUSTER = 5
# A rise counts as one when the recent count is at least this much higher
# than the previous one, and at least ``RISING_MIN_INCREASE`` records more.
RISING_FACTOR = 1.5
RISING_MIN_INCREASE = 2


def read_ticker_topics(
    db: Session,
    symbol: str,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> TickerTopics:
    """The ticker's content topics with their trends and clusters.

    Raises ``TickerNotFound`` for a symbol with no ticker.
    """
    ticker = find_ticker(db, symbol)
    now = now or datetime.now(timezone.utc)
    window_days = max(1, min(window_days, MAX_WINDOW_DAYS))
    counts = _counts(db, ticker.id, now)
    clusters = _clusters(db, ticker.id, now - timedelta(days=window_days))
    return TickerTopics(
        symbol=ticker.symbol,
        window_days=window_days,
        trend_days=TREND_DAYS,
        topics=[
            TickerTopic(
                topic=definition.identifier,
                label=definition.label,
                description=definition.description,
                recent_count=counts.get(definition.identifier, (0, 0))[0],
                previous_count=counts.get(definition.identifier, (0, 0))[1],
                trend=trend(*counts.get(definition.identifier, (0, 0))),
                clusters=clusters.get(definition.identifier, [])[:CLUSTERS_PER_TOPIC],
            )
            for definition in TOPICS
        ],
    )


def trend(recent: int, previous: int) -> TopicTrend:
    """How a topic's recent count compares with the period before it."""
    if recent == 0 and previous == 0:
        return "quiet"
    if previous == 0:
        return "new"
    if recent >= previous * RISING_FACTOR and recent - previous >= RISING_MIN_INCREASE:
        return "rising"
    if recent * RISING_FACTOR <= previous:
        return "falling"
    return "steady"


def _counts(db: Session, ticker_id, now: datetime) -> dict[str, tuple[int, int]]:
    """Distinct records per topic in the recent and the previous period."""
    date_value = func.coalesce(Artifact.published_at, Artifact.created_at)
    recent_start = now - timedelta(days=TREND_DAYS)
    previous_start = recent_start - timedelta(days=TREND_DAYS)
    recent = func.count(func.distinct(Artifact.id)).filter(date_value >= recent_start)
    previous = func.count(func.distinct(Artifact.id)).filter(
        and_(date_value >= previous_start, date_value < recent_start)
    )
    rows = (
        db.query(ArtifactContentTopic.topic, recent, previous)
        .join(Artifact, Artifact.id == ArtifactContentTopic.artifact_id)
        .filter(Artifact.ticker_id == ticker_id)
        .filter(date_value >= previous_start)
        .group_by(ArtifactContentTopic.topic)
        .all()
    )
    return {topic: (int(recent_count), int(previous_count)) for topic, recent_count, previous_count in rows}


def _clusters(db: Session, ticker_id, since: datetime) -> dict[str, list[TopicClusterView]]:
    """The ticker's clusters seen since ``since``, newest first, grouped by topic."""
    clusters = (
        db.query(ContentTopicCluster)
        .filter(ContentTopicCluster.ticker_id == ticker_id)
        .filter(ContentTopicCluster.last_published_at >= since)
        .filter(ContentTopicCluster.members.any())
        .order_by(ContentTopicCluster.last_published_at.desc(), ContentTopicCluster.id)
        .all()
    )
    if not clusters:
        return {}
    date_value = func.coalesce(Artifact.published_at, Artifact.created_at)
    rows = (
        db.query(ContentTopicClusterMember.cluster_id, Artifact, ArtifactContentTopic)
        .join(Artifact, Artifact.id == ContentTopicClusterMember.artifact_id)
        .join(ContentTopicCluster, ContentTopicCluster.id == ContentTopicClusterMember.cluster_id)
        .join(
            ArtifactContentTopic,
            and_(
                ArtifactContentTopic.artifact_id == Artifact.id,
                ArtifactContentTopic.topic == ContentTopicCluster.topic,
            ),
        )
        .options(selectinload(Artifact.platform))
        .filter(ContentTopicClusterMember.cluster_id.in_([cluster.id for cluster in clusters]))
        .order_by(date_value.desc().nullslast(), Artifact.id.desc())
        .all()
    )
    members: dict = defaultdict(list)
    for cluster_id, artifact, topic in rows:
        members[cluster_id].append((artifact, topic))

    grouped: dict[str, list[TopicClusterView]] = defaultdict(list)
    for cluster in clusters:
        records = members.get(cluster.id, [])
        if not records:
            continue
        grouped[cluster.topic].append(
            TopicClusterView(
                id=cluster.id,
                label=cluster.label,
                first_published_at=cluster.first_published_at,
                last_published_at=cluster.last_published_at,
                artifact_count=len(records),
                records=[_record(artifact, topic) for artifact, topic in records[:RECORDS_PER_CLUSTER]],
            )
        )
    return grouped


def _record(artifact: Artifact, topic: ArtifactContentTopic) -> TopicClusterRecord:
    return TopicClusterRecord(
        id=artifact.id,
        title=(artifact.title or "").strip() or "Untitled record",
        tag=artifact_card.tag(artifact),
        source_type=(artifact.source_type or "").strip() or "market_update",
        date=record_date(artifact),
        published_at=artifact.published_at or artifact.created_at,
        confidence=float(topic.confidence),
        method=topic.method,
        evidence=topic.evidence,
        event_label=topic.event_label,
        sources=artifact_card.sources(artifact),
    )
