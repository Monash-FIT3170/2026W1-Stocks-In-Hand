from sqlalchemy.orm import Session
from uuid import UUID
from app.models.claim_source import ClaimSource
from app.schemas.claim_source import ClaimSourceCreate

def get_claim_source(db: Session, claim_source_id: UUID):
    return db.query(ClaimSource).filter(ClaimSource.id == claim_source_id).first()

def get_sources_by_claim(db: Session, claim_id: UUID):
    return db.query(ClaimSource).filter(ClaimSource.claim_id == claim_id).all()

def create_claim_source(db: Session, claim_source: ClaimSourceCreate):
    db_cs = ClaimSource(**claim_source.model_dump())
    db.add(db_cs)
    db.commit()
    db.refresh(db_cs)
    return db_cs