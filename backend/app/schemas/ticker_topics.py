from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.ticker_brief import SourceLink

TopicTrend = Literal["new", "rising", "steady", "falling", "quiet"]


class TopicClusterRecord(BaseModel):
    """One artifact in a topic cluster, with the evidence for its topic."""

    id: UUID
    title: str
    tag: str
    source_type: str
    date: str
    published_at: Optional[datetime]
    confidence: float
    method: str
    # A verbatim source passage that shows the topic, or None.
    evidence: Optional[str]
    event_label: Optional[str]
    sources: list[SourceLink]


class TopicClusterView(BaseModel):
    """One development under one topic, and the artifacts that report it."""

    id: UUID
    label: str
    first_published_at: datetime
    last_published_at: datetime
    artifact_count: int
    records: list[TopicClusterRecord]


class TickerTopic(BaseModel):
    """One content topic for a ticker: how much it has come up, and its clusters."""

    topic: str
    label: str
    description: str
    # Distinct artifacts recorded with the topic in the last and the previous
    # ``trend_days`` days.
    recent_count: int
    previous_count: int
    trend: TopicTrend
    clusters: list[TopicClusterView]


class TickerTopics(BaseModel):
    """Every content topic for one ticker, in taxonomy order."""

    symbol: str
    window_days: int
    trend_days: int
    topics: list[TickerTopic]
