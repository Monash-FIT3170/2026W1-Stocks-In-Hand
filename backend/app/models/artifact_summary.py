from sqlalchemy import Column, String, DateTime, Text, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database.base import Base

class ArtifactSummary(Base):
    __tablename__ = "artifact_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False)
    summary_text = Column(Text, nullable=False)
    model_used = Column(String, nullable=True)
    prompt_version = Column(String, nullable=True)
    confidence_score = Column(Numeric, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # relationships
    artifact = relationship("Artifact", backref="summaries")