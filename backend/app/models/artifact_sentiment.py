from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database.base import Base

class ArtifactSentiment(Base):
    __tablename__ = "artifact_sentiments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False)
    sentiment_label = Column(String, nullable=False)
    stance = Column(String, nullable=True)
    confidence_score = Column(Numeric, nullable=True)
    model_used = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # relationships
    artifact = relationship("Artifact", backref="sentiments")