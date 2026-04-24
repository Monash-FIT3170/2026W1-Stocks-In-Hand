from sqlalchemy.orm import Session
from uuid import UUID
from app.models.artifact_topic import ArtifactTopic
from app.schemas.artifact_topic import ArtifactTopicCreate

def get_topics_by_artifact(db: Session, artifact_id: UUID):
    return db.query(ArtifactTopic).filter(ArtifactTopic.artifact_id == artifact_id).all()

def get_artifacts_by_topic(db: Session, topic_id: UUID):
    return db.query(ArtifactTopic).filter(ArtifactTopic.topic_id == topic_id).all()

def create_artifact_topic(db: Session, artifact_topic: ArtifactTopicCreate):
    db_at = ArtifactTopic(**artifact_topic.model_dump())
    db.add(db_at)
    db.commit()
    db.refresh(db_at)
    return db_at