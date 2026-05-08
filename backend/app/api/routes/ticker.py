from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.ticker import TickerCreate, TickerResponse
from app.crud import ticker as crud

router = APIRouter(prefix="/tickers", tags=["tickers"])

@router.post("/", response_model=TickerResponse)
def create_ticker(ticker: TickerCreate, db: Session = Depends(get_db)):
    existing = crud.get_ticker_by_symbol(db, symbol=ticker.symbol)
    if existing:
        raise HTTPException(status_code=400, detail="Ticker symbol already exists")
    return crud.create_ticker(db=db, ticker=ticker)

@router.get("/", response_model=list[TickerResponse])
def get_tickers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_tickers(db, skip=skip, limit=limit)

@router.get("/symbol/{symbol}", response_model=TickerResponse)
def get_ticker_by_symbol(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker

@router.get("/{ticker_id}", response_model=TickerResponse)
def get_ticker(ticker_id: UUID, db: Session = Depends(get_db)):
    ticker = crud.get_ticker(db, ticker_id=ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker

@router.patch("/{ticker_id}", response_model=TickerResponse)
def update_ticker(ticker_id: UUID, data: dict, db: Session = Depends(get_db)):
    ticker = crud.get_ticker(db, ticker_id=ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return crud.update_ticker(db=db, ticker_id=ticker_id, data=data)