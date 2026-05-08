from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.artifact_sentiment import ArtifactSentimentCreate, ArtifactSentimentResponse
from app.crud import artifact_sentiment as crud

router = APIRouter(prefix="/artifact-sentiments", tags=["artifact-sentiments"])

@router.post("/", response_model=ArtifactSentimentResponse)
def create_artifact_sentiment(sentiment: ArtifactSentimentCreate, db: Session = Depends(get_db)):
    return crud.create_artifact_sentiment(db=db, sentiment=sentiment)

@router.get("/artifact/{artifact_id}", response_model=list[ArtifactSentimentResponse])
def get_sentiments_by_artifact(artifact_id: UUID, db: Session = Depends(get_db)):
    sentiments = crud.get_sentiments_by_artifact(db, artifact_id=artifact_id)
    if not sentiments:
        raise HTTPException(status_code=404, detail="No sentiments found for this artifact")
    return sentiments

@router.get("/{sentiment_id}", response_model=ArtifactSentimentResponse)
def get_artifact_sentiment(sentiment_id: UUID, db: Session = Depends(get_db)):
    sentiment = crud.get_artifact_sentiment(db, sentiment_id=sentiment_id)
    if not sentiment:
        raise HTTPException(status_code=404, detail="Sentiment not found")
    return sentiment