from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WatchlistTickerBase(BaseModel):
    watchlist_id: UUID
    ticker_id: UUID


class WatchlistTickerCreate(WatchlistTickerBase):
    pass


class WatchlistTickerResponse(WatchlistTickerBase):
    added_at: datetime

    model_config = {"from_attributes": True}
