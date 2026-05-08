from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional, Any
from decimal import Decimal

class InformationPlatformCreate(BaseModel):
    name: str
    platform_type: str
    base_url: Optional[str] = None
    credibility_score: Optional[Decimal] = None
    scrape_enabled: bool = True
    scrape_config: Optional[dict[str, Any]] = None

class InformationPlatformResponse(BaseModel):
    id: UUID
    name: str
    platform_type: str
    base_url: Optional[str]
    credibility_score: Optional[Decimal]
    scrape_enabled: bool
    scrape_config: Optional[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}