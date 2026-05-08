from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.claim_source import ClaimSourceCreate, ClaimSourceResponse
from app.crud import claim_source as crud

router = APIRouter(prefix="/claim-sources", tags=["claim-sources"])

@router.post("/", response_model=ClaimSourceResponse)
def create_claim_source(claim_source: ClaimSourceCreate, db: Session = Depends(get_db)):
    return crud.create_claim_source(db=db, claim_source=claim_source)

@router.get("/claim/{claim_id}", response_model=list[ClaimSourceResponse])
def get_sources_by_claim(claim_id: UUID, db: Session = Depends(get_db)):
    sources = crud.get_sources_by_claim(db, claim_id=claim_id)
    if not sources:
        raise HTTPException(status_code=404, detail="No sources found for this claim")
    return sources

@router.get("/{claim_source_id}", response_model=ClaimSourceResponse)
def get_claim_source(claim_source_id: UUID, db: Session = Depends(get_db)):
    source = crud.get_claim_source(db, claim_source_id=claim_source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Claim source not found")
    return source