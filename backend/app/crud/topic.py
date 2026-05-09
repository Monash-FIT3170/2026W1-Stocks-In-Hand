from sqlalchemy.orm import Session
from uuid import UUID
from app.models.topic import Topic
from app.schemas.topic import TopicCreate

def get_topic(db: Session, topic_id: UUID):
    return db.query(Topic).filter(Topic.id == topic_id).first()

def get_topic_by_name(db: Session, name: str):
    return db.query(Topic).filter(Topic.name == name).first()

def get_topics(db: Session):
    return db.query(Topic).all()

def create_topic(db: Session, topic: TopicCreate):
    db_topic = Topic(**topic.model_dump())
    db.add(db_topic)
    db.commit()
    db.refresh(db_topic)
    return db_topic