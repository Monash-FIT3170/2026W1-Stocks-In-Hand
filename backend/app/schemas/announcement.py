from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AnnouncementResponse(BaseModel):
    id: UUID
    ticker: str
    tag: str
    source_type: str
    source_name: str
    source_label: str
    published_at: Optional[datetime]
    title: str
    about: str
    changed: str
    matters: str
    url: Optional[str]


class TrendingAnnouncementResponse(BaseModel):
    symbol: str
    count: int
