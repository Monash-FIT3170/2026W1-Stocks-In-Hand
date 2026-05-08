from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.watchlist_ticker import WatchlistTickerResponse
from app.crud import watchlist_ticker as crud

router = APIRouter(prefix="/watchlist-tickers", tags=["watchlist-tickers"])

@router.post("/{watchlist_id}/{ticker_id}", response_model=WatchlistTickerResponse)
def add_ticker_to_watchlist(watchlist_id: UUID, ticker_id: UUID, db: Session = Depends(get_db)):
    return crud.add_ticker_to_watchlist(db=db, watchlist_id=watchlist_id, ticker_id=ticker_id)

@router.get("/{watchlist_id}", response_model=list[WatchlistTickerResponse])
def get_watchlist_tickers(watchlist_id: UUID, db: Session = Depends(get_db)):
    tickers = crud.get_watchlist_tickers(db, watchlist_id=watchlist_id)
    if not tickers:
        raise HTTPException(status_code=404, detail="No tickers found for this watchlist")
    return tickers

@router.delete("/{watchlist_id}/{ticker_id}")
def remove_ticker_from_watchlist(watchlist_id: UUID, ticker_id: UUID, db: Session = Depends(get_db)):
    crud.remove_ticker_from_watchlist(db=db, watchlist_id=watchlist_id, ticker_id=ticker_id)
    return {"message": "Ticker removed from watchlist successfully"}