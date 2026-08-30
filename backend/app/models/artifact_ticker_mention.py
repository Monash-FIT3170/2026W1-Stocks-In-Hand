import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base import Base


class ArtifactTickerMention(Base):
    """A verified link between one public post and one ticker."""

    __tablename__ = "artifact_ticker_mentions"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "ticker_id",
            name="uq_artifact_ticker_mentions_artifact_ticker",
        ),
        CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_artifact_ticker_mentions_confidence_range",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticker_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tickers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    match_method = Column(String(length=64), nullable=False)
    match_confidence = Column(Float, nullable=False)
    matched_text = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    artifact = relationship("Artifact", back_populates="ticker_mentions")
    ticker = relationship("Ticker", back_populates="artifact_mentions")
