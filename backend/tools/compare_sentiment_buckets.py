"""Compare the taxonomy sentiment buckets with the keyword ones they replaced, writing nothing.

Run from ``backend/``, best with read-only database credentials::

    python -m tools.compare_sentiment_buckets [--ticker BHP] [--days 365] [--limit 250]

For each catalogue ticker, or the one given, it reads the analysed
artifacts the category sentiment view reads. For each bucket it prints how
many count in it and their dominant label under the keyword rule the view
used to follow and under the view's taxonomy rule, and how many of the
taxonomy rule's were placed by its keyword fallback. Then it lists each
artifact whose buckets differ. The session runs in a read-only transaction
and is rolled back.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.read_models import ticker_sentiment
from app.read_models.ticker_records import TickerNotFound, find_ticker
from app.read_models.ticker_sentiment import CATEGORY_SENTIMENT_KEYS, AnalysedRow
from app.sources import SOURCES


@dataclass(frozen=True)
class Bucket:
    """How many analysed artifacts count in a bucket, and their dominant label."""

    count: int
    label: str | None


@dataclass(frozen=True)
class Move:
    """An artifact the two rules put in different buckets."""

    title: str
    keyword: tuple[str, ...]
    taxonomy: tuple[str, ...]


@dataclass(frozen=True)
class Comparison:
    symbol: str
    analysed: int
    keyword: dict[str, Bucket]
    taxonomy: dict[str, Bucket]
    # How many of each taxonomy bucket's artifacts the keyword fallback placed.
    fallback: dict[str, int]
    moves: list[Move]


def compare(db: Session, symbol: str, *, days: int, limit: int) -> Comparison:
    """Both rules' buckets for one ticker. Raises ``TickerNotFound`` for an unknown one."""
    ticker = find_ticker(db, symbol)
    rows = ticker_sentiment.analysed_rows(db, ticker.id, days=days, limit=limit)
    keyword_rows: dict[str, list[AnalysedRow]] = {key: [] for key in CATEGORY_SENTIMENT_KEYS}
    taxonomy_rows: dict[str, list[AnalysedRow]] = {key: [] for key in CATEGORY_SENTIMENT_KEYS}
    fallback = dict.fromkeys(CATEGORY_SENTIMENT_KEYS, 0)
    moves: list[Move] = []
    for artifact, sentiment in rows:
        keyword = ticker_sentiment.keyword_buckets_for(artifact)
        taxonomy = ticker_sentiment.buckets_for(artifact)
        placed_by_keyword = ticker_sentiment.taxonomy_buckets_for(artifact) is None
        for bucket in keyword:
            keyword_rows[bucket].append((artifact, sentiment))
        for bucket in taxonomy:
            taxonomy_rows[bucket].append((artifact, sentiment))
            if placed_by_keyword:
                fallback[bucket] += 1
        if set(keyword) != set(taxonomy):
            title = artifact.title or str(artifact.id)
            moves.append(Move(title=title, keyword=keyword, taxonomy=taxonomy))
    return Comparison(
        symbol=ticker.symbol,
        analysed=len(rows),
        keyword=_buckets(keyword_rows),
        taxonomy=_buckets(taxonomy_rows),
        fallback=fallback,
        moves=moves,
    )


def report(comparison: Comparison) -> str:
    """The comparison as the lines the command prints."""
    lines = [
        f"{comparison.symbol}: {comparison.analysed} analysed artifacts",
        f"  {'bucket':<16} {'keyword rule':<22} {'taxonomy rule':<22} by keyword fallback",
    ]
    for bucket in CATEGORY_SENTIMENT_KEYS:
        lines.append(
            f"  {bucket:<16} {_cell(comparison.keyword[bucket]):<22} "
            f"{_cell(comparison.taxonomy[bucket]):<22} {comparison.fallback[bucket]}"
        )
    if comparison.moves:
        lines.append("  Moved:")
        lines.extend(
            f"    {move.title}: {_names(move.keyword)} -> {_names(move.taxonomy)}"
            for move in comparison.moves
        )
    return "\n".join(lines)


def _buckets(rows: dict[str, list[AnalysedRow]]) -> dict[str, Bucket]:
    return {
        bucket: Bucket(
            count=len(bucket_rows),
            label=ticker_sentiment.aggregate_bucket(bucket, bucket_rows).sentiment_label,
        )
        for bucket, bucket_rows in rows.items()
    }


def _cell(bucket: Bucket) -> str:
    return f"{bucket.count} {bucket.label}" if bucket.count else "0"


def _names(buckets: tuple[str, ...]) -> str:
    return ", ".join(buckets) or "no bucket"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare the keyword and taxonomy sentiment buckets without writing"
    )
    parser.add_argument("--ticker", help="one ticker instead of the whole catalogue")
    parser.add_argument("--days", type=int, default=ticker_sentiment.DEFAULT_SENTIMENT_DAYS)
    parser.add_argument("--limit", type=int, default=ticker_sentiment.DEFAULT_SENTIMENT_LIMIT)
    return parser


def main() -> int:
    """Print the comparison for each ticker asked for."""
    args = _parser().parse_args()
    symbols = [args.ticker] if args.ticker else sorted(SOURCES)

    from app.database.connection import (  # pylint: disable=import-outside-toplevel
        SessionLocal,
    )

    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        for symbol in symbols:
            try:
                print(report(compare(db, symbol, days=args.days, limit=args.limit)))
            except TickerNotFound:
                print(f"{symbol}: not in the database")
    finally:
        db.rollback()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
