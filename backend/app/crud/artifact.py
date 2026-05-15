from sqlalchemy.orm import Session
from uuid import UUID
from app.models.artifact import Artifact
from app.schemas.artifact import ArtifactCreate

def get_artifact(db: Session, artifact_id: UUID):
    return db.query(Artifact).filter(Artifact.id == artifact_id).first()

def get_artifacts_by_ticker(db: Session, ticker_id: UUID):
    return db.query(Artifact).filter(Artifact.ticker_id == ticker_id).all()

def get_artifacts_by_platform(db: Session, platform_id: UUID):
    return db.query(Artifact).filter(Artifact.platform_id == platform_id).all()

def get_all_artifacts(db: Session, limit: int = 200, offset: int = 0):
    return db.query(Artifact).order_by(Artifact.published_at.desc()).offset(offset).limit(limit).all()

def create_artifact(db: Session, artifact: ArtifactCreate):
    db_artifact = Artifact(**artifact.model_dump())
    db.add(db_artifact)
    db.commit()
    db.refresh(db_artifact)
    return db_artifact

def get_artifact_by_hash(db: Session, content_hash: str):
    return db.query(Artifact).filter(Artifact.content_hash == content_hash).first()

def get_platform_by_name(db: Session, name: str):
    from app.models.information_platform import InformationPlatform
    return db.query(InformationPlatform).filter(InformationPlatform.name == name).first()