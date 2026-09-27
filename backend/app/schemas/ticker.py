from pydantic import BaseModel, field_validator
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

class TickerUpdate(BaseModel):
    """Descriptive fields an administrator may correct on an existing ticker."""

    company_name: Optional[str] = None
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[Decimal] = None

    model_config = {"extra": "forbid"}

    @field_validator("company_name", "exchange")
    @classmethod
    def reject_null(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            raise ValueError("must not be null")
        return value

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