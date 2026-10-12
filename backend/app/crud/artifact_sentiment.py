from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.artifact_sentiment import ArtifactSentiment
from app.schemas.artifact_sentiment import ArtifactSentimentCreate

def get_artifact_sentiment(db: Session, sentiment_id: UUID):
    return db.query(ArtifactSentiment).filter(ArtifactSentiment.id == sentiment_id).first()

def get_sentiments_by_artifact(db: Session, artifact_id: UUID):
    return db.query(ArtifactSentiment).filter(ArtifactSentiment.artifact_id == artifact_id).all()


def stage_artifact_sentiment(
    db: Session,
    *,
    artifact_id: UUID,
    sentiment_label: str,
    stance: str | None = None,
    confidence_score: Decimal | float | None = None,
    model_used: str | None = None,
) -> ArtifactSentiment:
    """Find-or-create the single sentiment row for an artifact and stage
    field changes on it, without committing.

    Use this (instead of `upsert_artifact_sentiment`) when the caller is
    already managing its own transaction and commit/retry — e.g.
    `crud.artifact.store_artifact_analysis`, which stages the artifact,
    summary, and sentiment rows together and commits them in one
    transaction. Standalone callers should use `upsert_artifact_sentiment`.
    """
    row = (
        db.query(ArtifactSentiment)
        .filter(ArtifactSentiment.artifact_id == artifact_id)
        .first()
    )
    if row is None:
        row = ArtifactSentiment(
            artifact_id=artifact_id,
            sentiment_label=sentiment_label,
        )
        db.add(row)
    row.sentiment_label = sentiment_label
    row.stance = stance
    row.confidence_score = confidence_score
    row.model_used = model_used
    return row


def upsert_artifact_sentiment(
    db: Session,
    *,
    artifact_id: UUID,
    sentiment_label: str,
    stance: str | None = None,
    confidence_score: Decimal | float | None = None,
    model_used: str | None = None,
) -> ArtifactSentiment:
    """Create or update the single sentiment row for an artifact, retrying
    once if a concurrent writer raced us to create the row."""
    row = stage_artifact_sentiment(
        db,
        artifact_id=artifact_id,
        sentiment_label=sentiment_label,
        stance=stance,
        confidence_score=confidence_score,
        model_used=model_used,
    )
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        row = (
            db.query(ArtifactSentiment)
            .filter(ArtifactSentiment.artifact_id == artifact_id)
            .one()
        )
        row.sentiment_label = sentiment_label
        row.stance = stance
        row.confidence_score = confidence_score
        row.model_used = model_used
        db.commit()
        db.refresh(row)
        return row


def create_artifact_sentiment(db: Session, sentiment: ArtifactSentimentCreate):
    return upsert_artifact_sentiment(db, **sentiment.model_dump())
