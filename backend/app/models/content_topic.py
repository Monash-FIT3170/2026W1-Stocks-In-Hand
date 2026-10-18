"""Content topics recorded for artifacts, and the topic clusters that group them."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.content_topic_vocabulary import CONTENT_TOPICS, TOPIC_METHODS
from app.database.base import Base


def _one_of(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class ArtifactContentTopic(Base):
    """One content topic an artifact discusses, with how it was decided and its evidence."""

    __tablename__ = "artifact_content_topics"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "topic",
            name="uq_artifact_content_topics_artifact_topic",
        ),
        CheckConstraint(
            _one_of("topic", CONTENT_TOPICS),
            name="ck_artifact_content_topics_topic",
        ),
        CheckConstraint(
            _one_of("method", TOPIC_METHODS),
            name="ck_artifact_content_topics_method",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_artifact_content_topics_confidence_range",
        ),
        Index("ix_artifact_content_topics_topic_artifact", "topic", "artifact_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic = Column(String(length=64), nullable=False)
    confidence = Column(Float, nullable=False)
    method = Column(String(length=16), nullable=False)
    # A verbatim source passage that shows the topic, when one was found.
    evidence = Column(Text, nullable=True)
    # A short label of the development, which clustering matches on.
    event_label = Column(Text, nullable=True)
    # The prompt version or rules version that decided the topic.
    version = Column(String(length=64), nullable=False)
    model_used = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    artifact = relationship("Artifact", back_populates="content_topics")


class ContentTopicCluster(Base):
    """One ticker's artifacts about one development under one topic."""

    __tablename__ = "content_topic_clusters"
    __table_args__ = (
        CheckConstraint(
            _one_of("topic", CONTENT_TOPICS),
            name="ck_content_topic_clusters_topic",
        ),
        Index(
            "ix_content_topic_clusters_ticker_topic_last",
            "ticker_id",
            "topic",
            "last_published_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tickers.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic = Column(String(length=64), nullable=False)
    label = Column(Text, nullable=False)
    # The words its members' event labels and titles use, sorted and joined by spaces.
    signature = Column(Text, nullable=False, default="")
    first_published_at = Column(DateTime(timezone=True), nullable=False)
    last_published_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    ticker = relationship("Ticker")
    members = relationship(
        "ContentTopicClusterMember",
        back_populates="cluster",
        cascade="all, delete-orphan",
    )


class ContentTopicClusterMember(Base):
    """An artifact in a topic cluster."""

    __tablename__ = "content_topic_cluster_members"
    __table_args__ = (
        UniqueConstraint(
            "cluster_id",
            "artifact_id",
            name="uq_content_topic_cluster_members_cluster_artifact",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(
        UUID(as_uuid=True),
        ForeignKey("content_topic_clusters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    cluster = relationship("ContentTopicCluster", back_populates="members")
    artifact = relationship("Artifact")
