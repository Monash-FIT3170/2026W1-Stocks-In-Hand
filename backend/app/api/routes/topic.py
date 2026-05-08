from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.topic import TopicCreate, TopicResponse
from app.crud import topic as crud

router = APIRouter(prefix="/topics", tags=["topics"])

@router.post("/", response_model=TopicResponse)
def create_topic(topic: TopicCreate, db: Session = Depends(get_db)):
    existing = crud.get_topic_by_name(db, name=topic.name)
    if existing:
        raise HTTPException(status_code=400, detail="Topic already exists")
    return crud.create_topic(db=db, topic=topic)

@router.get("/", response_model=list[TopicResponse])
def get_topics(db: Session = Depends(get_db)):
    return crud.get_topics(db)

@router.get("/{topic_id}", response_model=TopicResponse)
def get_topic(topic_id: UUID, db: Session = Depends(get_db)):
    topic = crud.get_topic(db, topic_id=topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic