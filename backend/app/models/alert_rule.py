import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql import func, true

from app.database.base import Base


class AlertRule(Base):
    """An investor's threshold for sentiment-driven watchlist alerts."""

    __tablename__ = "alert_rules"
    __table_args__ = (
        UniqueConstraint(
            "investor_id",
            "ticker_id",
            "rule_type",
            name="uq_alert_rules_investor_ticker_type",
        ),
        Index(
            "ux_alert_rules_global",
            "investor_id",
            "rule_type",
            unique=True,
            postgresql_where=text("ticker_id IS NULL"),
        ),
        Index("ix_alert_rules_ticker_id", "ticker_id"),
        CheckConstraint(
            "min_confidence >= 0 AND min_confidence <= 1",
            name="ck_alert_rules_min_confidence",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("investors.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tickers.id", ondelete="CASCADE"),
        nullable=True,
    )
    rule_type = Column(
        String,
        nullable=False,
        default="sentiment_threshold",
        server_default="sentiment_threshold",
    )
    sentiment_labels = Column(
        ARRAY(String),
        nullable=False,
        default=lambda: ["negative"],
        server_default=text("ARRAY['negative']::varchar[]"),
    )
    min_confidence = Column(
        Numeric(5, 4),
        nullable=False,
        default=0.75,
        server_default="0.75",
    )
    enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
