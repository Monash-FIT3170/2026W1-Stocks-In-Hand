from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.watchlist import WatchlistResponse


class WatchedSignal(BaseModel):
    """A watched company's latest signal."""

    model_config = {"from_attributes": True, "protected_namespaces": ()}

    sentiment_label: str
    confidence_score: Optional[float] = None
    model_used: Optional[str] = None
    analyzed_at: Optional[datetime] = None


class WatchedCompany(BaseModel):
    ticker_id: UUID
    symbol: str
    company_name: str
    exchange: Optional[str] = None
    sector: Optional[str] = None
    added_at: Optional[datetime] = None
    latest_signal: Optional[WatchedSignal] = None
    # The brief line of the company's latest record, None until it has a summary.
    brief: Optional[str] = None
    # When that record was published, or collected when it has no date.
    last_brief_at: Optional[datetime] = None


class WatchlistSummary(BaseModel):
    """An investor's watchlist page: the watchlist, or None, and its companies."""

    watchlist: Optional[WatchlistResponse]
    companies: list[WatchedCompany]
