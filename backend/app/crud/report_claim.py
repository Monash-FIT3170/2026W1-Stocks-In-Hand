from sqlalchemy.orm import Session
from uuid import UUID
from app.models.report_claim import ReportClaim
from app.schemas.report_claim import ReportClaimCreate

def get_claims_by_report(db: Session, report_id: UUID):
    return db.query(ReportClaim).filter(ReportClaim.report_id == report_id).all()

def get_report_claim(db: Session, report_id: UUID, claim_id: UUID):
    return (
        db.query(ReportClaim)
        .filter(
            ReportClaim.report_id == report_id,
            ReportClaim.claim_id == claim_id,
        )
        .first()
    )

def create_report_claim(db: Session, report_claim: ReportClaimCreate):
    db_rc = ReportClaim(**report_claim.model_dump())
    db.add(db_rc)
    db.commit()
    db.refresh(db_rc)
    return db_rc

def delete_report_claim(db: Session, report_id: UUID, claim_id: UUID):
    db_rc = get_report_claim(db, report_id, claim_id)
    if db_rc is None:
        return None
    db.delete(db_rc)
    db.commit()
    return db_rc
