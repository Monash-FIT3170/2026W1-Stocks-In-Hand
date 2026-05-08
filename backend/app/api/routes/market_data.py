from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.market_data import MarketDataCreate, MarketDataResponse
from app.crud import market_data as crud

router = APIRouter(prefix="/market-data", tags=["market-data"])

@router.post("/", response_model=MarketDataResponse)
def create_market_data(market_data: MarketDataCreate, db: Session = Depends(get_db)):
    return crud.create_market_data(db=db, market_data=market_data)

@router.get("/ticker/{ticker_id}", response_model=list[MarketDataResponse])
def get_market_data_by_ticker(ticker_id: UUID, db: Session = Depends(get_db)):
    data = crud.get_market_data_by_ticker(db, ticker_id=ticker_id)
    if not data:
        raise HTTPException(status_code=404, detail="No market data found for this ticker")
    return data

@router.get("/ticker/{ticker_id}/latest", response_model=MarketDataResponse)
def get_latest_market_data(ticker_id: UUID, db: Session = Depends(get_db)):
    data = crud.get_latest_market_data(db, ticker_id=ticker_id)
    if not data:
        raise HTTPException(status_code=404, detail="No market data found for this ticker")
    return data

@router.get("/{market_data_id}", response_model=MarketDataResponse)
def get_market_data(market_data_id: UUID, db: Session = Depends(get_db)):
    data = crud.get_market_data(db, market_data_id=market_data_id)
    if not data:
        raise HTTPException(status_code=404, detail="Market data not found")
    return data