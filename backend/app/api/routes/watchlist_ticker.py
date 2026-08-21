from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.deps import get_current_investor
from app.database.connection import get_db
from app.models.investor import Investor
from app.schemas.watchlist_ticker import WatchlistTickerResponse
from app.crud import watchlist_ticker as crud
from app.crud import watchlist as watchlist_crud

router = APIRouter(prefix="/watchlist-tickers", tags=["watchlist-tickers"])


def _verify_watchlist_owner(db: Session, watchlist_id: UUID, investor_id: UUID):
    watchlist = watchlist_crud.get_watchlist(db, watchlist_id=watchlist_id)
    if not watchlist or watchlist.investor_id != investor_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")


@router.post("/{watchlist_id}/{ticker_id}", response_model=WatchlistTickerResponse)
def add_ticker_to_watchlist(
    watchlist_id: UUID,
    ticker_id: UUID,
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
):
    _verify_watchlist_owner(db, watchlist_id, current_investor.id)
    return crud.add_ticker_to_watchlist(db=db, watchlist_id=watchlist_id, ticker_id=ticker_id)


@router.get("/{watchlist_id}", response_model=list[WatchlistTickerResponse])
def get_watchlist_tickers(
    watchlist_id: UUID,
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
):
    _verify_watchlist_owner(db, watchlist_id, current_investor.id)
    return crud.get_watchlist_tickers(db, watchlist_id=watchlist_id) or []


@router.delete("/{watchlist_id}/{ticker_id}")
def remove_ticker_from_watchlist(
    watchlist_id: UUID,
    ticker_id: UUID,
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
):
    _verify_watchlist_owner(db, watchlist_id, current_investor.id)
    crud.remove_ticker_from_watchlist(db=db, watchlist_id=watchlist_id, ticker_id=ticker_id)
    return {"message": "Ticker removed from watchlist successfully"}