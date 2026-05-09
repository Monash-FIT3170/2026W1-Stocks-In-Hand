import uuid

from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database.base import Base


class MarketData(Base):
    __tablename__ = "market_data"
    __table_args__ = (
        UniqueConstraint("ticker_id", "price_date", name="uq_market_data_ticker_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=False)
    price_date = Column(Date, nullable=False)
    open_price = Column(Numeric, nullable=True)
    high_price = Column(Numeric, nullable=True)
    low_price = Column(Numeric, nullable=True)
    close_price = Column(Numeric, nullable=True)
    adjusted_close_price = Column(Numeric, nullable=True)
    volume = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
