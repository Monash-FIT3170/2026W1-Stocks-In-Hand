from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.deps import get_current_investor
from app.database.connection import get_db
from app.models.investor import Investor
from app.schemas.watchlist import WatchlistCreate, WatchlistResponse
from app.crud import watchlist as crud

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


@router.post("", response_model=WatchlistResponse)
@router.post("/", response_model=WatchlistResponse)
def create_watchlist(
    watchlist: WatchlistCreate,
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
):
    # Enforce that the watchlist is tied to the authenticated investor
    watchlist.investor_id = current_investor.id
    return crud.create_watchlist(db=db, watchlist=watchlist)


@router.get("/me", response_model=list[WatchlistResponse])
def get_my_watchlists(
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
):
    return crud.get_watchlists_by_investor(db, investor_id=current_investor.id) or []


@router.get("/investor/{investor_id}", response_model=list[WatchlistResponse])
def get_watchlists_by_investor(
    investor_id: UUID,
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
):
    if current_investor.id != investor_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return crud.get_watchlists_by_investor(db, investor_id=investor_id) or []


@router.get("/{watchlist_id}", response_model=WatchlistResponse)
def get_watchlist(
    watchlist_id: UUID,
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
):
    watchlist = crud.get_watchlist(db, watchlist_id=watchlist_id)
    if not watchlist or watchlist.investor_id != current_investor.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    return watchlist


@router.delete("/{watchlist_id}")
def delete_watchlist(
    watchlist_id: UUID,
    db: Session = Depends(get_db),
    current_investor: Investor = Depends(get_current_investor),
):
    watchlist = crud.get_watchlist(db, watchlist_id=watchlist_id)
    if not watchlist or watchlist.investor_id != current_investor.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    crud.delete_watchlist(db=db, watchlist_id=watchlist_id)
    return {"message": "Watchlist deleted successfully"}
