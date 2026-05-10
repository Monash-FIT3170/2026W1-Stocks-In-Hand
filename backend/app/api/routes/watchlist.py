from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.watchlist import WatchlistCreate, WatchlistResponse
from app.crud import watchlist as crud

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

@router.post("/", response_model=WatchlistResponse)
def create_watchlist(watchlist: WatchlistCreate, db: Session = Depends(get_db)):
    return crud.create_watchlist(db=db, watchlist=watchlist)

@router.get("/investor/{investor_id}", response_model=list[WatchlistResponse])
def get_watchlists_by_investor(investor_id: UUID, db: Session = Depends(get_db)):
    watchlists = crud.get_watchlists_by_investor(db, investor_id=investor_id)
    if not watchlists:
        raise HTTPException(status_code=404, detail="No watchlists found for this investor")
    return watchlists

@router.get("/{watchlist_id}", response_model=WatchlistResponse)
def get_watchlist(watchlist_id: UUID, db: Session = Depends(get_db)):
    watchlist = crud.get_watchlist(db, watchlist_id=watchlist_id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return watchlist

@router.patch("/{watchlist_id}", response_model=WatchlistResponse)
def update_watchlist(watchlist_id: UUID, data: dict, db: Session = Depends(get_db)):
    watchlist = crud.get_watchlist(db, watchlist_id=watchlist_id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return crud.update_watchlist(db=db, watchlist_id=watchlist_id, data=data)

@router.delete("/{watchlist_id}")
def delete_watchlist(watchlist_id: UUID, db: Session = Depends(get_db)):
    watchlist = crud.get_watchlist(db, watchlist_id=watchlist_id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    crud.delete_watchlist(db=db, watchlist_id=watchlist_id)
    return {"message": "Watchlist deleted successfully"}
