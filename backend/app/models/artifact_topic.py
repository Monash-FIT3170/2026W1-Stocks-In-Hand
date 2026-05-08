from sqlalchemy import Column, Numeric, ForeignKey, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.base import Base

class ArtifactTopic(Base):
    __tablename__ = "artifact_topics"

    artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False)
    topic_id = Column(UUID(as_uuid=True), ForeignKey("topics.id"), nullable=False)
    confidence_score = Column(Numeric, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("artifact_id", "topic_id"),
    )

    # relationships
    artifact = relationship("Artifact", backref="artifact_topics")
    topic = relationship("Topic", backref="artifact_topics")