from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database.base import Base


class WatchlistTicker(Base):
    __tablename__ = "watchlist_tickers"

    watchlist_id = Column(
        UUID(as_uuid=True),
        ForeignKey("watchlists.id"),
        primary_key=True,
    )
    ticker_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tickers.id"),
        primary_key=True,
    )
    added_at = Column(DateTime(timezone=True), server_default=func.now())
