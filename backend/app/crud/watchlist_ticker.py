"""Database access for the watchlist-to-ticker association."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.watchlist import Watchlist
from app.models.watchlist_ticker import WatchlistTicker


def get_watchlist_tickers(
    db: Session,
    watchlist_id: UUID,
) -> list[WatchlistTicker]:
    """Return every ticker association for one watchlist."""
    return (
        db.query(WatchlistTicker)
        .filter(WatchlistTicker.watchlist_id == watchlist_id)
        .all()
    )


def add_ticker_to_watchlist(
    db: Session,
    watchlist_id: UUID,
    ticker_id: UUID,
) -> WatchlistTicker:
    """Add a ticker once and return its watchlist association."""
    existing = (
        db.query(WatchlistTicker)
        .filter(
            WatchlistTicker.watchlist_id == watchlist_id,
            WatchlistTicker.ticker_id == ticker_id,
        )
        .first()
    )
    if existing is not None:
        return existing

    db_wt = WatchlistTicker(watchlist_id=watchlist_id, ticker_id=ticker_id)
    db.add(db_wt)
    db.commit()
    db.refresh(db_wt)
    return db_wt


def remove_ticker_from_watchlist(
    db: Session,
    watchlist_id: UUID,
    ticker_id: UUID,
) -> None:
    """Remove one ticker association when it exists."""
    db_wt = (
        db.query(WatchlistTicker)
        .filter(
            WatchlistTicker.watchlist_id == watchlist_id,
            WatchlistTicker.ticker_id == ticker_id,
        )
        .first()
    )
    if db_wt is None:
        return

    db.delete(db_wt)
    db.commit()


def investor_ids_watching(db: Session, ticker_id: UUID) -> list[UUID]:
    """Return each investor watching a ticker, even when watchlists overlap."""
    statement = (
        select(Watchlist.investor_id)
        .join(
            WatchlistTicker,
            WatchlistTicker.watchlist_id == Watchlist.id,
        )
        .where(WatchlistTicker.ticker_id == ticker_id)
        .distinct()
    )
    return list(db.scalars(statement))
