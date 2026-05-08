from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.scrape_run import ScrapeRunCreate, ScrapeRunResponse
from app.crud import scrape_run as crud

router = APIRouter(prefix="/scrape-runs", tags=["scrape-runs"])

@router.post("/", response_model=ScrapeRunResponse)
def create_scrape_run(scrape_run: ScrapeRunCreate, db: Session = Depends(get_db)):
    return crud.create_scrape_run(db=db, scrape_run=scrape_run)

@router.get("/ticker/{ticker_id}", response_model=list[ScrapeRunResponse])
def get_scrape_runs_by_ticker(ticker_id: UUID, db: Session = Depends(get_db)):
    runs = crud.get_scrape_runs_by_ticker(db, ticker_id=ticker_id)
    if not runs:
        raise HTTPException(status_code=404, detail="No scrape runs found for this ticker")
    return runs

@router.get("/{scrape_run_id}", response_model=ScrapeRunResponse)
def get_scrape_run(scrape_run_id: UUID, db: Session = Depends(get_db)):
    run = crud.get_scrape_run(db, scrape_run_id=scrape_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Scrape run not found")
    return run