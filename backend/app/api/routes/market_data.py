from datetime import date, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.crud import market_data as crud
from app.crud import ticker as ticker_crud
from app.database.connection import get_db
from app.schemas.market_data import MarketDataCreate, MarketDataResponse

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


_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}


@router.post("/fetch/{symbol}")
async def fetch_market_data(symbol: str, db: Session = Depends(get_db)):
    ticker = ticker_crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    yahoo_symbol = f"{symbol.upper()}.AX"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=_YAHOO_HEADERS)

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Yahoo Finance returned {resp.status_code}")

    result = resp.json().get("chart", {}).get("result") or []
    if not result:
        raise HTTPException(status_code=502, detail="No data in Yahoo Finance response")

    meta = result[0].get("meta", {})
    current_price = meta.get("regularMarketPrice")
    prev_close = meta.get("chartPreviousClose") or meta.get("regularMarketPreviousClose")

    if not current_price:
        raise HTTPException(status_code=502, detail="Could not parse price from Yahoo Finance")

    today = date.today()
    crud.upsert_market_data(db, ticker_id=ticker.id, price_date=today, close_price=current_price)
    if prev_close:
        crud.upsert_market_data(
            db, ticker_id=ticker.id, price_date=today - timedelta(days=1), close_price=prev_close
        )

    return {"symbol": symbol.upper(), "price": current_price, "prev_close": prev_close}