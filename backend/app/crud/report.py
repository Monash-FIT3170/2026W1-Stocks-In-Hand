from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from uuid import UUID
from app.models.report import Report
from app.models.report_claim import ReportClaim
from app.models.claim import Claim
from app.models.claim_source import ClaimSource
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment

def get_report(db: Session, report_id: UUID):
    return (
        db.query(Report)
        .options(
            joinedload(Report.report_claims)
            .joinedload(ReportClaim.claim)
            .joinedload(Claim.claim_sources)
            .joinedload(ClaimSource.artifact)
        )
        .filter(Report.id == report_id)
        .first()
    )

def get_reports_by_ticker(db: Session, ticker_id: UUID):
    return db.query(Report).filter(Report.ticker_id == ticker_id).all()

def get_latest_report_for_ticker(db: Session, ticker_id: UUID):
    return (
        db.query(Report)
        .filter(Report.ticker_id == ticker_id)
        .order_by(Report.created_at.desc())
        .first()
    )

def get_report_sentiment(db: Session, report_id: UUID):
    result = (
        db.query(func.avg(ArtifactSentiment.confidence_score))
        .join(Artifact, ArtifactSentiment.artifact_id == Artifact.id)
        .join(ClaimSource, ClaimSource.artifact_id == Artifact.id)
        .join(Claim, Claim.id == ClaimSource.claim_id)
        .join(ReportClaim, ReportClaim.claim_id == Claim.id)
        .filter(ReportClaim.report_id == report_id)
        .scalar()
    )
    return result

def create_report(db: Session, report):
    db_report = Report(**report.model_dump())
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report