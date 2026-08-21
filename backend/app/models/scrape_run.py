import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base import Base


class ScrapeRun(Base):
    """Durable state for one website-discovery request."""

    __tablename__ = "scrape_runs"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_scrape_runs_idempotency_key",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_id = Column(
        UUID(as_uuid=True),
        ForeignKey("information_platforms.id"),
        nullable=False,
    )
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=True)
    status = Column(String, nullable=False)
    source_url = Column(Text, nullable=True)
    idempotency_key = Column(String, nullable=True)
    trigger_type = Column(String, nullable=False, default="manual")
    queued_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    items_found = Column(Integer, default=0)
    items_saved = Column(Integer, default=0)
    items_downloaded = Column(Integer, nullable=False, default=0)
    items_analyzed = Column(Integer, nullable=False, default=0)
    items_failed = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    artifacts = relationship("Artifact", back_populates="scrape_run")
