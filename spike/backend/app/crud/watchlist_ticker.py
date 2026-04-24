from sqlalchemy.orm import Session
from uuid import UUID
from app.models.watchlist_ticker import WatchlistTicker

def get_watchlist_tickers(db: Session, watchlist_id: UUID):
    return db.query(WatchlistTicker).filter(WatchlistTicker.watchlist_id == watchlist_id).all()

def add_ticker_to_watchlist(db: Session, watchlist_id: UUID, ticker_id: UUID):
    db_wt = WatchlistTicker(watchlist_id=watchlist_id, ticker_id=ticker_id)
    db.add(db_wt)
    db.commit()
    db.refresh(db_wt)
    return db_wt

def remove_ticker_from_watchlist(db: Session, watchlist_id: UUID, ticker_id: UUID):
    db_wt = db.query(WatchlistTicker).filter(
        WatchlistTicker.watchlist_id == watchlist_id,
        WatchlistTicker.ticker_id == ticker_id
    ).first()
    db.delete(db_wt)
    db.commit()