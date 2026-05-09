from sqlalchemy.orm import Session
from uuid import UUID
from app.models.claim import Claim
from app.schemas.claim import ClaimCreate

def get_claim(db: Session, claim_id: UUID):
    return db.query(Claim).filter(Claim.id == claim_id).first()

def get_claims_by_artifact(db: Session, artifact_id: UUID):
    return db.query(Claim).filter(Claim.artifact_id == artifact_id).all()

def create_claim(db: Session, claim: ClaimCreate):
    db_claim = Claim(**claim.model_dump())
    db.add(db_claim)
    db.commit()
    db.refresh(db_claim)
    return db_claim