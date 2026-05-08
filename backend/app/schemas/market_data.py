from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class MarketDataBase(BaseModel):
    ticker_id: UUID
    price_date: date
    open_price: Optional[Decimal] = None
    high_price: Optional[Decimal] = None
    low_price: Optional[Decimal] = None
    close_price: Optional[Decimal] = None
    adjusted_close_price: Optional[Decimal] = None
    volume: Optional[int] = None


class MarketDataCreate(MarketDataBase):
    pass


class MarketDataResponse(MarketDataBase):
    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}
