from sqlalchemy.orm import Session
from uuid import UUID
from app.models.artifact_summary import ArtifactSummary
from app.schemas.artifact_summary import ArtifactSummaryCreate

def get_artifact_summary(db: Session, summary_id: UUID):
    return db.query(ArtifactSummary).filter(ArtifactSummary.id == summary_id).first()

def get_summaries_by_artifact(db: Session, artifact_id: UUID):
    return db.query(ArtifactSummary).filter(ArtifactSummary.artifact_id == artifact_id).all()

def create_artifact_summary(db: Session, summary: ArtifactSummaryCreate):
    db_summary = ArtifactSummary(**summary.model_dump())
    db.add(db_summary)
    db.commit()
    db.refresh(db_summary)
    return db_summary