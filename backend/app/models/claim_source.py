import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.base import Base


class ClaimSource(Base):
    __tablename__ = "claim_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id"), nullable=False)
    artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False)
    chunk_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifact_chunks.id"),
        nullable=True,
    )
    evidence_text = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    claim = relationship("Claim", back_populates="claim_sources")
    artifact = relationship("Artifact", back_populates="claim_sources")
    chunk = relationship("ArtifactChunk", backref="claim_sources")
