from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.artifact_topic import ArtifactTopicCreate, ArtifactTopicResponse
from app.crud import artifact_topic as crud

router = APIRouter(prefix="/artifact-topics", tags=["artifact-topics"])

@router.post("/", response_model=ArtifactTopicResponse)
def create_artifact_topic(artifact_topic: ArtifactTopicCreate, db: Session = Depends(get_db)):
    return crud.create_artifact_topic(db=db, artifact_topic=artifact_topic)

@router.get("/artifact/{artifact_id}", response_model=list[ArtifactTopicResponse])
def get_topics_by_artifact(artifact_id: UUID, db: Session = Depends(get_db)):
    topics = crud.get_topics_by_artifact(db, artifact_id=artifact_id)
    if not topics:
        raise HTTPException(status_code=404, detail="No topics found for this artifact")
    return topics

@router.get("/topic/{topic_id}", response_model=list[ArtifactTopicResponse])
def get_artifacts_by_topic(topic_id: UUID, db: Session = Depends(get_db)):
    artifacts = crud.get_artifacts_by_topic(db, topic_id=topic_id)
    if not artifacts:
        raise HTTPException(status_code=404, detail="No artifacts found for this topic")
    return artifacts