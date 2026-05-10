from sqlalchemy.orm import Session
from uuid import UUID
from app.models.report_claim import ReportClaim
from app.schemas.report_claim import ReportClaimCreate

def get_claims_by_report(db: Session, report_id: UUID):
    return db.query(ReportClaim).filter(ReportClaim.report_id == report_id).all()

def create_report_claim(db: Session, report_claim: ReportClaimCreate):
    db_rc = ReportClaim(**report_claim.model_dump())
    db.add(db_rc)
    db.commit()
    db.refresh(db_rc)
    return db_rc