from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from typing import Optional
from decimal import Decimal

class TickerCreate(BaseModel):
    symbol: str
    company_name: str
    exchange: str = "ASX"
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[Decimal] = None

class TickerResponse(BaseModel):
    id: UUID
    symbol: str
    company_name: str
    exchange: str
    sector: Optional[str]
    industry: Optional[str]
    market_cap: Optional[Decimal]
    created_at: datetime

    model_config = {"from_attributes": True}