"""Database access for artifact content topics and topic clusters.

``record_topics`` replaces an artifact's topics whole and places the artifact
in a topic cluster for each topic, inside the caller's transaction. It takes
a transaction-scoped advisory lock per ticker and topic, so two analysis
workers recording the same ticker's topics at once cannot both start a
cluster for one development. The caller commits.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.content_topic_vocabulary import (
    TOPICS_METHOD_KEY,
    TOPICS_MODEL_KEY,
    TOPICS_TAGGED_AT_KEY,
    TOPICS_VERSION_KEY,
)
from app.models.artifact import Artifact
from app.models.content_topic import (
    ArtifactContentTopic,
    ContentTopicCluster,
    ContentTopicClusterMember,
)
from parsing.content_topics import (
    Candidate,
    choose_cluster,
    decode_signature,
    encode_signature,
    merged_signature,
    signature,
)

# The most recent clusters an artifact is compared with, per ticker and topic.
CANDIDATE_CLUSTERS = 50
MAX_CLUSTER_LABEL_CHARS = 160


@dataclass(frozen=True)
class TopicRecord:
    """One topic to record for an artifact."""

    topic: str
    confidence: float
    method: str
    evidence: str | None
    event_label: str | None


def record_topics(  # pylint: disable=too-many-arguments
    db: Session,
    artifact: Artifact,
    topics: Sequence[TopicRecord],
    *,
    version: str,
    method: str,
    model: str | None,
    window_days: int,
    now: datetime | None = None,
) -> list[ContentTopicCluster]:
    """Replace the artifact's topics and cluster it under each one.

    Its old topic rows and cluster memberships are deleted first, so tagging
    again never leaves a stale topic. An artifact with no ticker is recorded
    but joins no cluster. The tagging version is written to its metadata
    even when it has no topics, so a tagging run does not select it again.
    Returns the clusters it joined or started.
    """
    db.execute(
        delete(ContentTopicClusterMember).where(
            ContentTopicClusterMember.artifact_id == artifact.id
        )
    )
    # Deleted through the relationship, and flushed before the new rows, so
    # the loaded collection stays current and a topic recorded again cannot
    # collide with its old row.
    artifact.content_topics.clear()
    db.flush()
    for record in topics:
        artifact.content_topics.append(
            ArtifactContentTopic(
                topic=record.topic,
                confidence=float(record.confidence),
                method=record.method,
                evidence=record.evidence,
                event_label=record.event_label,
                version=version,
                model_used=model,
            )
        )
    tagged_at = now or datetime.now(timezone.utc)
    artifact.artifact_metadata = {
        **(artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}),
        TOPICS_VERSION_KEY: version,
        TOPICS_METHOD_KEY: method,
        TOPICS_MODEL_KEY: model,
        TOPICS_TAGGED_AT_KEY: tagged_at.isoformat(),
    }
    if artifact.ticker_id is None:
        db.flush()
        return []

    published_at = _published_at(artifact, tagged_at)
    clusters = [
        _join_cluster(
            db,
            ticker_id=artifact.ticker_id,
            topic=record.topic,
            words=signature(record.event_label, artifact.title),
            label=record.event_label or artifact.title or "",
            artifact_id=artifact.id,
            published_at=published_at,
            window_days=window_days,
        )
        for record in topics
    ]
    db.flush()
    return clusters


def _join_cluster(  # pylint: disable=too-many-arguments
    db: Session,
    *,
    ticker_id: UUID,
    topic: str,
    words: frozenset[str],
    label: str,
    artifact_id: UUID,
    published_at: datetime,
    window_days: int,
) -> ContentTopicCluster:
    lock_key = func.hashtext(f"content-topic:{ticker_id}:{topic}")
    db.execute(select(func.pg_advisory_xact_lock(lock_key)))
    window = timedelta(days=window_days)
    rows = db.scalars(
        select(ContentTopicCluster)
        .where(
            ContentTopicCluster.ticker_id == ticker_id,
            ContentTopicCluster.topic == topic,
            ContentTopicCluster.last_published_at >= published_at - window,
            ContentTopicCluster.first_published_at <= published_at + window,
        )
        .order_by(ContentTopicCluster.last_published_at.desc(), ContentTopicCluster.id)
        .limit(CANDIDATE_CLUSTERS)
    ).all()
    by_id = {row.id: row for row in rows}
    chosen = choose_cluster(
        [
            Candidate(
                cluster_id=row.id,
                signature=decode_signature(row.signature),
                first_published_at=row.first_published_at,
                last_published_at=row.last_published_at,
            )
            for row in rows
        ],
        words,
        published_at,
        window_days=window_days,
    )
    if chosen is None:
        cluster = ContentTopicCluster(
            ticker_id=ticker_id,
            topic=topic,
            label=_label(label),
            signature=encode_signature(words),
            first_published_at=published_at,
            last_published_at=published_at,
        )
        db.add(cluster)
        db.flush()
    else:
        cluster = by_id[chosen]
        cluster.signature = encode_signature(
            merged_signature(decode_signature(cluster.signature), words)
        )
        cluster.first_published_at = min(cluster.first_published_at, published_at)
        if published_at >= cluster.last_published_at:
            cluster.last_published_at = published_at
            # The newest member's development names the cluster.
            if label.strip():
                cluster.label = _label(label)
    db.add(ContentTopicClusterMember(cluster_id=cluster.id, artifact_id=artifact_id))
    return cluster


def topic_filter(topic: str) -> Any:
    """A query filter for artifacts recorded with ``topic``."""
    return Artifact.content_topics.any(ArtifactContentTopic.topic == topic)


def _published_at(artifact: Artifact, fallback: datetime) -> datetime:
    value = artifact.published_at or artifact.created_at or fallback
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _label(text: str) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:MAX_CLUSTER_LABEL_CHARS] or "Untitled development"
