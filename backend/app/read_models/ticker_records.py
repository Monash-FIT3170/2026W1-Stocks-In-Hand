"""Ticker records: which ticker a page asks about, and which artifacts are its records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.crud import ticker as ticker_crud
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.services import artifact_summary


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


def recent_artifacts(db: Session, ticker_id: UUID, *, limit: int) -> list[Artifact]:
    """The newest artifacts stored against a ticker, latest published first.

    Artifacts with no publication date come after the dated ones, newest
    collected first. Each comes with its summary and platform, so reading
    their cards and summaries runs no query per artifact.
    """
    return (
        db.query(Artifact)
        .options(artifact_summary.WITH_SUMMARY, selectinload(Artifact.platform))
        .filter(Artifact.ticker_id == ticker_id)
        .order_by(Artifact.published_at.desc().nullslast(), Artifact.created_at.desc())
        .limit(limit)
        .all()
    )


def record_date(artifact: Artifact) -> str:
    """The day an artifact was published, as a page shows it, or "Recently"."""
    published_at = artifact.published_at
    if not published_at:
        return "Recently"
    return f"{published_at.strftime('%b')} {published_at.day}, {published_at.year}"
