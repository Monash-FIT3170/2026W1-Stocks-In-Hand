from enum import Enum
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
from uuid import UUID


class SourceType(str, Enum):
    ASX_ANNOUNCEMENT = "asx_announcement"
    REDDIT           = "reddit"
    NEWS             = "news"
    HOTCOPPER        = "hotcopper"


class ArtifactType(str, Enum):
    # Document types with reliable pypdf/regex extractors
    DIVIDEND_ANNOUNCEMENT  = "dividend_announcement"
    SECURITY_NOTIFICATION  = "security_notification"
    LEADERSHIP_CHANGE      = "leadership_change"
    # Catch-alls for types that cannot be reliably parsed without AI
    ASX_ANNOUNCEMENT_OTHER = "asx_announcement_other"
    REDDIT_POST            = "reddit_post"
    HOTCOPPER_POST         = "hotcopper_post"
    NEWS_ARTICLE           = "news_article"


class ArtifactCreate(BaseModel):
    # required
    source_type:        SourceType
    artifact_type:      ArtifactType
    title:              str
    url:                str
    published_at:       datetime
    content_hash:       str
    raw_text:           str
    # optional — genuinely not always available
    ticker_id:          Optional[UUID] = None
    platform_id:        Optional[UUID] = None
    author:             Optional[str] = None
    artifact_metadata:  Optional[dict[str, Any]] = None
    credibility_label:  Optional[str] = None


class ArtifactResponse(BaseModel):
    id: UUID
    ticker_id: Optional[UUID]
    platform_id: Optional[UUID]
    source_type: Optional[str]
    artifact_type: str
    title: Optional[str]
    url: Optional[str]
    author: Optional[str]
    published_at: Optional[datetime]
    scraped_at: datetime
    is_duplicate: bool
    duplicate_of_id: Optional[UUID]
    credibility_label: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
