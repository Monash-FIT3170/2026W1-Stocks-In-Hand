from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.report_claim import ReportClaimCreate, ReportClaimResponse
from app.crud import report_claim as crud

router = APIRouter(prefix="/report-claims", tags=["report-claims"])

@router.post("/", response_model=ReportClaimResponse)
def create_report_claim(report_claim: ReportClaimCreate, db: Session = Depends(get_db)):
    return crud.create_report_claim(db=db, report_claim=report_claim)

@router.get("/report/{report_id}", response_model=list[ReportClaimResponse])
def get_claims_by_report(report_id: UUID, db: Session = Depends(get_db)):
    claims = crud.get_claims_by_report(db, report_id=report_id)
    if not claims:
        raise HTTPException(status_code=404, detail="No claims found for this report")
    return claims

@router.get("/{report_id}/{claim_id}", response_model=ReportClaimResponse)
def get_report_claim(report_id: UUID, claim_id: UUID, db: Session = Depends(get_db)):
    report_claim = crud.get_report_claim(db, report_id=report_id, claim_id=claim_id)
    if not report_claim:
        raise HTTPException(status_code=404, detail="Report claim not found")
    return report_claim

@router.delete("/{report_id}/{claim_id}")
def delete_report_claim(report_id: UUID, claim_id: UUID, db: Session = Depends(get_db)):
    report_claim = crud.delete_report_claim(db, report_id=report_id, claim_id=claim_id)
    if not report_claim:
        raise HTTPException(status_code=404, detail="Report claim not found")
    return {"message": "Report claim deleted successfully"}
