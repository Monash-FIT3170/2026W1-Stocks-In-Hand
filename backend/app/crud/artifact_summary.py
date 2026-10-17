from uuid import UUID

from sqlalchemy.orm import Session

from app.models.artifact_summary import ArtifactSummary

def get_artifact_summary(db: Session, summary_id: UUID):
    return db.query(ArtifactSummary).filter(ArtifactSummary.id == summary_id).first()

def get_summaries_by_artifact(db: Session, artifact_id: UUID):
    return db.query(ArtifactSummary).filter(ArtifactSummary.artifact_id == artifact_id).all()
