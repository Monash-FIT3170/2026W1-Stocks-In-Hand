from enum import Enum
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
from uuid import UUID


class SourceType(str, Enum):
    ASX_ANNOUNCEMENT = "asx_announcement"
    REDDIT           = "reddit"
    BLUESKY          = "bluesky"
    MASTODON         = "mastodon"
    NEWS             = "news"
    HOTCOPPER        = "hotcopper"


class ArtifactType(str, Enum):
    DIVIDEND_ANNOUNCEMENT  = "dividend_announcement"
    SECURITY_NOTIFICATION  = "security_notification"
    LEADERSHIP_CHANGE      = "leadership_change"
    ASX_ANNOUNCEMENT_OTHER = "asx_announcement_other"
    REDDIT_POST            = "reddit_post"
    BLUESKY_POST           = "bluesky_post"
    MASTODON_POST          = "mastodon_post"
    HOTCOPPER_POST         = "hotcopper_post"
    NEWS_ARTICLE           = "news_article"


class ArtifactCreate(BaseModel):
    source_type:        SourceType
    artifact_type:      ArtifactType
    title:              str
    url:                str
    published_at:       datetime
    content_hash:       str
    raw_text:           str
    ticker_id:          Optional[UUID] = None
    platform_id:        Optional[UUID] = None
    scrape_run_id:      Optional[UUID] = None
    source_adapter:     Optional[str] = None
    source_id:          Optional[str] = None
    canonical_url:      Optional[str] = None
    document_url:       Optional[str] = None
    author:             Optional[str] = None
    artifact_metadata:  Optional[dict[str, Any]] = None


class ArtifactResponse(BaseModel):
    id: UUID
    scrape_run_id: Optional[UUID]
    ticker_id: Optional[UUID]
    platform_id: Optional[UUID]
    source_type: Optional[str]
    artifact_type: str
    title: Optional[str]
    url: Optional[str]
    author: Optional[str]
    published_at: Optional[datetime]
    scraped_at: datetime
    artifact_metadata: Optional[dict[str, Any]] = None
    raw_text: Optional[str] = None
    source_id: Optional[str] = None
    source_adapter: Optional[str] = None
    canonical_url: Optional[str] = None
    document_url: Optional[str] = None
    checksum_sha256: Optional[str] = None
    content_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    s3_bucket: Optional[str] = None
    s3_key: Optional[str] = None
    download_status: str
    analysis_status: str
    downloaded_at: Optional[datetime] = None
    analyzed_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
