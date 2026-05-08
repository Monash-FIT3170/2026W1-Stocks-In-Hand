from sqlalchemy.orm import Session
from uuid import UUID
from app.models.extracted_fact import ExtractedFact
from app.schemas.extracted_fact import ExtractedFactCreate

def get_extracted_fact(db: Session, fact_id: UUID):
    return db.query(ExtractedFact).filter(ExtractedFact.id == fact_id).first()

def get_facts_by_artifact(db: Session, artifact_id: UUID):
    return db.query(ExtractedFact).filter(ExtractedFact.artifact_id == artifact_id).all()

def get_facts_by_chunk(db: Session, chunk_id: UUID):
    return db.query(ExtractedFact).filter(ExtractedFact.chunk_id == chunk_id).all()

def create_extracted_fact(db: Session, fact: ExtractedFactCreate):
    db_fact = ExtractedFact(**fact.model_dump())
    db.add(db_fact)
    db.commit()
    db.refresh(db_fact)
    return db_fact