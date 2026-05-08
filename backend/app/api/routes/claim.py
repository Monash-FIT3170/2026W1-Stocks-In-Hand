from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.claim import ClaimCreate, ClaimResponse
from app.crud import claim as crud

router = APIRouter(prefix="/claims", tags=["claims"])

@router.post("/", response_model=ClaimResponse)
def create_claim(claim: ClaimCreate, db: Session = Depends(get_db)):
    return crud.create_claim(db=db, claim=claim)

@router.get("/artifact/{artifact_id}", response_model=list[ClaimResponse])
def get_claims_by_artifact(artifact_id: UUID, db: Session = Depends(get_db)):
    claims = crud.get_claims_by_artifact(db, artifact_id=artifact_id)
    if not claims:
        raise HTTPException(status_code=404, detail="No claims found for this artifact")
    return claims

@router.get("/{claim_id}", response_model=ClaimResponse)
def get_claim(claim_id: UUID, db: Session = Depends(get_db)):
    claim = crud.get_claim(db, claim_id=claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim