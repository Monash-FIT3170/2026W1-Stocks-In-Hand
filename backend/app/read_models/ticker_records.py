"""Ticker records: which ticker a page asks about, and the artifacts that are its records.

A ticker's records are the artifacts stored against it, newest published
first. Its news feed shows each as its artifact card, and its deep dive as
an entry of its research history with the summary's text. Both read the
summaries loaded with the records, so neither runs a query per record. The
newest record is the one the ticker's brief and watchlist card tell.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.crud import ticker as ticker_crud
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.schemas.ticker_records import DeepDiveEvent, NewsFeedRecord
from app.services import artifact_card, artifact_summary

# How many records the news feed and the deep dive show.
PAGE_RECORDS = 10
# Latest published first. Records with no publication date come after the
# dated ones, newest collected first.
_NEWEST_FIRST = (Artifact.published_at.desc().nullslast(), Artifact.created_at.desc())


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


def read_news_feed(db: Session, symbol: str) -> list[NewsFeedRecord]:
    """The ticker's newest records, each as its artifact card.

    Raises ``TickerNotFound`` for a symbol with no ticker.
    """
    ticker = find_ticker(db, symbol)
    return [
        NewsFeedRecord(
            id=artifact.id,
            ticker=ticker.symbol,
            time=record_date(artifact),
            **artifact_card.artifact_card(artifact).fields(),
            sources=artifact_card.sources(artifact),
        )
        for artifact in recent_artifacts(db, ticker.id, limit=PAGE_RECORDS)
    ]


def read_deep_dive(db: Session, symbol: str) -> list[DeepDiveEvent]:
    """The ticker's newest records as its research history. No records, no history.

    Raises ``TickerNotFound`` for a symbol with no ticker.
    """
    ticker = find_ticker(db, symbol)
    events: list[DeepDiveEvent] = []
    for artifact in recent_artifacts(db, ticker.id, limit=PAGE_RECORDS):
        summary = artifact_summary.read(artifact)
        events.append(
            DeepDiveEvent(
                tag=artifact_card.tag(artifact),
                title=artifact.title or f"{ticker.symbol} update",
                date=record_date(artifact),
                detail=summary.text if summary else None,
                sources=artifact_card.sources(artifact),
            )
        )
    return events


def recent_artifacts(db: Session, ticker_id: UUID, *, limit: int) -> list[Artifact]:
    """A ticker's newest records.

    Each comes with its summary and platform, so reading their cards and
    summaries runs no query per artifact.
    """
    return (
        db.query(Artifact)
        .options(artifact_summary.WITH_SUMMARY, selectinload(Artifact.platform))
        .filter(Artifact.ticker_id == ticker_id)
        .order_by(*_NEWEST_FIRST)
        .limit(limit)
        .all()
    )


def latest_artifacts(db: Session, ticker_ids: Iterable[UUID]) -> dict[UUID, Artifact]:
    """Each ticker's newest record, with its summary, in one query for any number of tickers.

    A ticker with no records is left out.
    """
    ids = list(ticker_ids)
    if not ids:
        return {}
    artifacts = (
        db.query(Artifact)
        .options(artifact_summary.WITH_SUMMARY)
        .filter(Artifact.ticker_id.in_(ids))
        .order_by(Artifact.ticker_id, *_NEWEST_FIRST)
        .distinct(Artifact.ticker_id)
        .all()
    )
    return {artifact.ticker_id: artifact for artifact in artifacts}


def record_date(artifact: Artifact) -> str:
    """The day an artifact was published, as a page shows it, or "Recently"."""
    published_at = artifact.published_at
    if not published_at:
        return "Recently"
    return f"{published_at.strftime('%b')} {published_at.day}, {published_at.year}"
