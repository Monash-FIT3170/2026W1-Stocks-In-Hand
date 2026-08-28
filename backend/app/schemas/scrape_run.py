from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ScrapeRunBase(BaseModel):
    platform_id: UUID
    ticker_id: Optional[UUID] = None
    status: str
    source_url: Optional[str] = None
    idempotency_key: Optional[str] = None
    trigger_type: str = "manual"
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    items_found: int = 0
    items_saved: int = 0
    items_downloaded: int = 0
    items_analyzed: int = 0
    items_failed: int = 0
    error_message: Optional[str] = None


class ScrapeRunCreate(ScrapeRunBase):
    pass


class ScrapeRunResponse(ScrapeRunBase):
    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ScrapeEnqueueResponse(BaseModel):
    status: str
    ticker: str
    scrape_run_id: UUID
