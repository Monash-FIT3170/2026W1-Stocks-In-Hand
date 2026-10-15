from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AnnouncementResponse(BaseModel):
    id: UUID
    ticker: str
    tag: str
    source_type: str
    source_name: Optional[str]
    source_label: str
    published_at: Optional[datetime]
    title: str
    # None until the artifact has a summary with that line.
    about: Optional[str]
    changed: Optional[str]
    matters: Optional[str]
    url: Optional[str]


class TrendingAnnouncementResponse(BaseModel):
    symbol: str
    count: int
