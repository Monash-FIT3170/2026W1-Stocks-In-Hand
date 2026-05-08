from sqlalchemy.orm import Session
from uuid import UUID
from app.models.artifact_sentiment import ArtifactSentiment
from app.schemas.artifact_sentiment import ArtifactSentimentCreate

def get_artifact_sentiment(db: Session, sentiment_id: UUID):
    return db.query(ArtifactSentiment).filter(ArtifactSentiment.id == sentiment_id).first()

def get_sentiments_by_artifact(db: Session, artifact_id: UUID):
    return db.query(ArtifactSentiment).filter(ArtifactSentiment.artifact_id == artifact_id).all()

def create_artifact_sentiment(db: Session, sentiment: ArtifactSentimentCreate):
    db_sentiment = ArtifactSentiment(**sentiment.model_dump())
    db.add(db_sentiment)
    db.commit()
    db.refresh(db_sentiment)
    return db_sentiment