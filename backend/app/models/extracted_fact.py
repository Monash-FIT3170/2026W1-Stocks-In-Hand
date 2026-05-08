from sqlalchemy import Column, String, DateTime, Text, Numeric, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database.base import Base

class ExtractedFact(Base):
    __tablename__ = "extracted_facts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("artifact_chunks.id"), nullable=True)
    fact_text = Column(Text, nullable=False)
    fact_type = Column(String, nullable=True)
    confidence_score = Column(Numeric, nullable=True)
    is_speculative = Column(Boolean, default=False)
    model_used = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # relationships
    artifact = relationship("Artifact", backref="extracted_facts")
    chunk = relationship("ArtifactChunk", backref="extracted_facts")