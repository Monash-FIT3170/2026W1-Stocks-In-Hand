from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.artifact_summary import ArtifactSummary
from app.schemas.artifact_summary import ArtifactSummaryCreate

def get_artifact_summary(db: Session, summary_id: UUID):
    return db.query(ArtifactSummary).filter(ArtifactSummary.id == summary_id).first()

def get_summaries_by_artifact(db: Session, artifact_id: UUID):
    return db.query(ArtifactSummary).filter(ArtifactSummary.artifact_id == artifact_id).all()


def upsert_artifact_summary(
    db: Session,
    *,
    artifact_id: UUID,
    summary_text: str,
    model_used: str | None = None,
    prompt_version: str | None = None,
    confidence_score: Decimal | float | None = None,
) -> ArtifactSummary:
    """Create or update the single summary row for an artifact."""
    row = (
        db.query(ArtifactSummary)
        .filter(ArtifactSummary.artifact_id == artifact_id)
        .first()
    )
    if row is None:
        row = ArtifactSummary(artifact_id=artifact_id, summary_text=summary_text)
        db.add(row)
    row.summary_text = summary_text
    row.model_used = model_used
    row.prompt_version = prompt_version
    row.confidence_score = confidence_score
    try:
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        row = (
            db.query(ArtifactSummary)
            .filter(ArtifactSummary.artifact_id == artifact_id)
            .one()
        )
        row.summary_text = summary_text
        row.model_used = model_used
        row.prompt_version = prompt_version
        row.confidence_score = confidence_score
        db.commit()
        db.refresh(row)
        return row


def create_artifact_summary(db: Session, summary: ArtifactSummaryCreate):
    return upsert_artifact_summary(db, **summary.model_dump())
