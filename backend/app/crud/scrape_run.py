from sqlalchemy.orm import Session
from uuid import UUID
from app.models.scrape_run import ScrapeRun
from app.schemas.scrape_run import ScrapeRunCreate

def get_scrape_run(db: Session, scrape_run_id: UUID):
    return db.query(ScrapeRun).filter(ScrapeRun.id == scrape_run_id).first()

def get_scrape_runs_by_ticker(db: Session, ticker_id: UUID):
    return db.query(ScrapeRun).filter(ScrapeRun.ticker_id == ticker_id).all()

def create_scrape_run(db: Session, scrape_run: ScrapeRunCreate):
    db_run = ScrapeRun(**scrape_run.model_dump())
    db.add(db_run)
    db.commit()
    db.refresh(db_run)
    return db_run