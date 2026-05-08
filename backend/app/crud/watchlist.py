from sqlalchemy.orm import Session
from uuid import UUID
from app.models.watchlist import Watchlist
from app.schemas.watchlist import WatchlistCreate

def get_watchlist(db: Session, watchlist_id: UUID):
    return db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()

def get_watchlists_by_investor(db: Session, investor_id: UUID):
    return db.query(Watchlist).filter(Watchlist.investor_id == investor_id).all()

def create_watchlist(db: Session, watchlist: WatchlistCreate):
    db_watchlist = Watchlist(**watchlist.model_dump())
    db.add(db_watchlist)
    db.commit()
    db.refresh(db_watchlist)
    return db_watchlist

def update_watchlist(db: Session, watchlist_id: UUID, data: dict):
    db_watchlist = get_watchlist(db, watchlist_id)
    for key, value in data.items():
        setattr(db_watchlist, key, value)
    db.commit()
    db.refresh(db_watchlist)
    return db_watchlist

def delete_watchlist(db: Session, watchlist_id: UUID):
    db_watchlist = get_watchlist(db, watchlist_id)
    db.delete(db_watchlist)
    db.commit()