import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database.base import Base


class Claim(Base):
    __tablename__ = "claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=False)
    claim_text = Column(Text, nullable=False)
    claim_type = Column(String, nullable=True)
    reliability_label = Column(String, nullable=True)
    confidence_score = Column(Numeric, nullable=True)
    generated_by_model = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
