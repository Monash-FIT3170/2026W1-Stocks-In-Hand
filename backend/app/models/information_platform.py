from sqlalchemy import Column, String, DateTime, Numeric, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid
from app.database.base import Base

class InformationPlatform(Base):
    __tablename__ = "information_platforms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    platform_type = Column(String, nullable=False)
    base_url = Column(String, nullable=True)
    credibility_score = Column(Numeric, nullable=True)
    scrape_enabled = Column(Boolean, default=True)
    scrape_config = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())