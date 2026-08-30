from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field


class CollectionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class PublicDiscussionPost(BaseModel):
    """Source-neutral post returned by a public discussion adapter."""

    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    title: str = ""
    url: str = Field(min_length=1)
    author: str | None = None
    raw_text: str = ""
    published_at: datetime | None = None
    engagement: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublicDiscussionCollectionResult(BaseModel):
    status: CollectionStatus
    posts: list[PublicDiscussionPost] = Field(default_factory=list)
    next_cursor: str | None = None
    error: str | None = None


class PublicDiscussionSource(BaseModel):
    source_type: str
    title: str | None = None
    url: str | None = None
    author: str | None = None
    published_at: datetime | None = None


class ArtifactTickerMentionCreate(BaseModel):
    artifact_id: UUID
    ticker_id: UUID
    match_method: str = Field(min_length=1, max_length=64)
    match_confidence: float = Field(ge=0, le=1)
    matched_text: str | None = None


class PublicDiscussionAnalysisCounts(BaseModel):
    total: int = 0
    pending: int = 0
    queued: int = 0
    analyzing: int = 0
    completed: int = 0
    failed: int = 0


class PublicDiscussionStatusResponse(BaseModel):
    ticker: str
    status: str
    counts: PublicDiscussionAnalysisCounts
    sources: dict[str, int] = Field(default_factory=dict)
    latest_collected_at: datetime | None = None


class PublicDiscussionRequeueResponse(BaseModel):
    execute: bool
    ticker: str | None = None
    candidates: int
    queued: int
    artifact_ids: list[UUID] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


@runtime_checkable
class PublicDiscussionAdapter(Protocol):
    """Contract implemented by Reddit, Bluesky, Mastodon and blog sources."""

    source_type: str

    def collect(
        self,
        query: str,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> PublicDiscussionCollectionResult: ...
