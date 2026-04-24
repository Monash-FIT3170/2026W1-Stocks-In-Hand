from sqlalchemy import Column, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database.base import Base

class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"), nullable=True)
    platform_id = Column(UUID(as_uuid=True), ForeignKey("information_platforms.id"), nullable=True)
    artifact_type = Column(String, nullable=False)
    title = Column(String, nullable=True)
    url = Column(String, nullable=True)
    author = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)
    raw_html = Column(Text, nullable=True)
    metadata = Column(JSONB, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    content_hash = Column(String, unique=True, nullable=True)
    is_duplicate = Column(Boolean, default=False)
    duplicate_of_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=True)
    credibility_label = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # relationships
    ticker = relationship("Ticker", backref="artifacts")
    platform = relationship("InformationPlatform", backref="artifacts")
    duplicate_of = relationship("Artifact", remote_side="Artifact.id", foreign_keys=[duplicate_of_id])