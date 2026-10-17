"""Watchlist summary: what an investor's watchlist page shows.

The page shows the investor's watchlist and, for each company on it, the
latest signal and the brief line of its latest record. The read runs the
same few queries however many companies are watched.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ticker import Ticker
from app.models.watchlist import Watchlist
from app.models.watchlist_ticker import WatchlistTicker
from app.read_models.ticker_records import latest_artifacts
from app.read_models.ticker_sentiment import latest_signals
from app.schemas.watchlist_summary import WatchedCompany, WatchlistSummary
from app.services import artifact_summary


def read_watchlist_summary(db: Session, investor_id: UUID) -> WatchlistSummary:
    """The investor's watchlist and its companies, in the order they were added.

    An investor with several watchlists sees the oldest. One with none gets
    no watchlist and no companies.
    """
    watchlist = (
        db.query(Watchlist)
        .filter(Watchlist.investor_id == investor_id)
        .order_by(Watchlist.created_at, Watchlist.id)
        .first()
    )
    if watchlist is None:
        return WatchlistSummary(watchlist=None, companies=[])

    watched = (
        db.query(WatchlistTicker.added_at, Ticker)
        .join(Ticker, Ticker.id == WatchlistTicker.ticker_id)
        .filter(WatchlistTicker.watchlist_id == watchlist.id)
        .order_by(WatchlistTicker.added_at, Ticker.symbol)
        .all()
    )
    ticker_ids = [ticker.id for _added_at, ticker in watched]
    signals = latest_signals(db, ticker_ids)
    latest = latest_artifacts(db, ticker_ids)

    companies = []
    for added_at, ticker in watched:
        artifact = latest.get(ticker.id)
        companies.append(
            WatchedCompany(
                ticker_id=ticker.id,
                symbol=ticker.symbol,
                company_name=ticker.company_name,
                exchange=ticker.exchange,
                sector=ticker.sector,
                added_at=added_at,
                latest_signal=signals.get(ticker.id),
                brief=artifact_summary.brief(artifact_summary.read(artifact)) if artifact else None,
                last_brief_at=(artifact.published_at or artifact.created_at) if artifact else None,
            )
        )
    return WatchlistSummary(watchlist=watchlist, companies=companies)
