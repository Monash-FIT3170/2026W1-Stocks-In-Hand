from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ScrapeRunBase(BaseModel):
    platform_id: UUID
    ticker_id: Optional[UUID] = None
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    items_found: int = 0
    items_saved: int = 0
    error_message: Optional[str] = None


class ScrapeRunCreate(ScrapeRunBase):
    pass


class ScrapeRunResponse(ScrapeRunBase):
    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}
