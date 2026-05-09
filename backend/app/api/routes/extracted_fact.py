from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.extracted_fact import ExtractedFactCreate, ExtractedFactResponse
from app.crud import extracted_fact as crud

router = APIRouter(prefix="/extracted-facts", tags=["extracted-facts"])

@router.post("/", response_model=ExtractedFactResponse)
def create_extracted_fact(fact: ExtractedFactCreate, db: Session = Depends(get_db)):
    return crud.create_extracted_fact(db=db, fact=fact)

@router.get("/artifact/{artifact_id}", response_model=list[ExtractedFactResponse])
def get_facts_by_artifact(artifact_id: UUID, db: Session = Depends(get_db)):
    facts = crud.get_facts_by_artifact(db, artifact_id=artifact_id)
    if not facts:
        raise HTTPException(status_code=404, detail="No facts found for this artifact")
    return facts

@router.get("/chunk/{chunk_id}", response_model=list[ExtractedFactResponse])
def get_facts_by_chunk(chunk_id: UUID, db: Session = Depends(get_db)):
    facts = crud.get_facts_by_chunk(db, chunk_id=chunk_id)
    if not facts:
        raise HTTPException(status_code=404, detail="No facts found for this chunk")
    return facts

@router.get("/{fact_id}", response_model=ExtractedFactResponse)
def get_extracted_fact(fact_id: UUID, db: Session = Depends(get_db)):
    fact = crud.get_extracted_fact(db, fact_id=fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")
    return fact