"""Ticker records: which ticker a page asks about, and which artifacts are its records."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.crud import ticker as ticker_crud
from app.models.ticker import Ticker


class TickerNotFound(LookupError):
    """No ticker is stored under the symbol a page asked for."""


def find_ticker(db: Session, symbol: str) -> Ticker:
    """The ticker stored under ``symbol``, given in any case, with or without ``.AX``.

    Raises ``TickerNotFound`` when there is none.
    """
    ticker = ticker_crud.get_ticker_by_symbol(db, symbol)
    if ticker is None:
        raise TickerNotFound(f"Ticker '{symbol}' not found")
    return ticker
