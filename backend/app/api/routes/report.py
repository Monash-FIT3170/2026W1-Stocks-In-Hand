from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.report import ReportCreate, ReportResponse
from app.crud import report as crud

router = APIRouter(prefix="/reports", tags=["reports"])

@router.post("/", response_model=ReportResponse)
def create_report(report: ReportCreate, db: Session = Depends(get_db)):
    return crud.create_report(db=db, report=report)

@router.get("/ticker/{ticker_id}", response_model=list[ReportResponse])
def get_reports_by_ticker(ticker_id: UUID, db: Session = Depends(get_db)):
    reports = crud.get_reports_by_ticker(db, ticker_id=ticker_id)
    if not reports:
        raise HTTPException(status_code=404, detail="No reports found for this ticker")
    return reports

@router.get("/ticker/{ticker_id}/latest", response_model=ReportResponse)
def get_latest_report(ticker_id: UUID, db: Session = Depends(get_db)):
    report = crud.get_latest_report_for_ticker(db, ticker_id=ticker_id)
    if not report:
        raise HTTPException(status_code=404, detail="No report found for this ticker")
    return report

@router.get("/{report_id}", response_model=ReportResponse)
def get_report(report_id: UUID, db: Session = Depends(get_db)):
    report = crud.get_report(db, report_id=report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report

@router.get("/{report_id}/sentiment")
def get_report_sentiment(report_id: UUID, db: Session = Depends(get_db)):
    report = crud.get_report(db, report_id=report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    sentiment = crud.get_report_sentiment(db, report_id=report_id)
    return {"report_id": report_id, "average_sentiment_score": sentiment}