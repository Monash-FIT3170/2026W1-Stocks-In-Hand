from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional, Any

class ArtifactCreate(BaseModel):
    ticker_id: Optional[UUID] = None
    platform_id: Optional[UUID] = None
    artifact_type: str
    title: Optional[str] = None
    url: Optional[str] = None
    author: Optional[str] = None
    raw_text: Optional[str] = None
    raw_html: Optional[str] = None
    artifact_metadata: Optional[dict[str, Any]] = None
    published_at: Optional[datetime] = None
    content_hash: Optional[str] = None
    credibility_label: Optional[str] = None

class ArtifactResponse(BaseModel):
    id: UUID
    ticker_id: Optional[UUID]
    platform_id: Optional[UUID]
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