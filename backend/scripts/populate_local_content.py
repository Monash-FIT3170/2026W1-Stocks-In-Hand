"""Populate a local database with bounded ASX, news, and Reddit content."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy.engine import make_url


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.routes import reddit
from app.core.config import settings
from app.database.connection import SessionLocal
from app.services import marketaux
from parsing.pipeline import process_announcement
from scrapers.base import Announcement
from scrapers.registry import get_scraper


LOCAL_DATABASE_HOSTS = {"127.0.0.1", "::1", "db", "localhost", "postgres"}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def bounded_announcements(
    announcements: Iterable[Announcement],
    *,
    lookback_days: int,
    max_documents: int,
    now: datetime | None = None,
) -> list[Announcement]:
    """Return the newest recent announcements within the configured cap."""
    if lookback_days < 1 or max_documents < 1:
        raise ValueError("lookback_days and max_documents must be positive")
    cutoff = _as_utc(now or datetime.now(timezone.utc)) - timedelta(
        days=lookback_days
    )
    recent = [
        announcement
        for announcement in announcements
        if _as_utc(announcement.date) >= cutoff
    ]
    return sorted(recent, key=lambda item: _as_utc(item.date), reverse=True)[
        :max_documents
    ]


def require_local_database() -> None:
    """Refuse to run this development loader against a remote database."""
    host = (make_url(settings.DATABASE_URL).host or "").lower()
    if host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError(
            "Local content loader refused a non-local database host"
        )


async def collect_asx(
    tickers: list[str],
    *,
    lookback_days: int,
    max_documents: int,
    output_dir: Path,
) -> dict:
    result = {"found": 0, "processed": 0, "errors": []}
    for ticker in tickers:
        scraper = get_scraper(ticker, output_dir)
        try:
            discovered = await scraper.fetch_announcements()
            selected = bounded_announcements(
                discovered,
                lookback_days=lookback_days,
                max_documents=max_documents,
            )
            result["found"] += len(selected)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append({"ticker": ticker, "stage": "discover", "error": str(exc)})
            continue

        for announcement in selected:
            try:
                announcement.local_path = await scraper.download_pdf(announcement)
                process_announcement(announcement)
                result["processed"] += 1
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(
                    {
                        "ticker": ticker,
                        "stage": "process",
                        "title": announcement.title,
                        "error": str(exc),
                    }
                )
    return result


def collect_news(tickers: list[str], *, limit: int) -> dict:
    if not settings.MARKETAUX_API_TOKEN:
        return {"status": "skipped", "reason": "MARKETAUX_API_TOKEN is not configured"}
    results = []
    with SessionLocal() as db:
        for ticker in tickers:
            try:
                results.append(marketaux.fetch_and_store_news(ticker, limit, db))
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                results.append({"symbol": ticker, "error": str(exc)})
    return {"status": "completed", "tickers": results}


def collect_reddit(*, subreddit: str, limit: int) -> dict:
    if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
        return {
            "status": "skipped",
            "reason": "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are not configured",
        }
    return {
        "status": "completed",
        **reddit._scrape_and_store_posts(subreddit=subreddit, limit=limit),
    }


async def populate(args: argparse.Namespace) -> dict:
    require_local_database()
    tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    selected_sources = {
        source.strip().lower() for source in args.sources.split(",") if source.strip()
    }
    unknown_sources = selected_sources - {"asx", "news", "reddit"}
    if unknown_sources:
        raise ValueError(f"Unsupported sources: {sorted(unknown_sources)}")

    results = {}
    if "asx" in selected_sources:
        results["asx"] = await collect_asx(
            tickers,
            lookback_days=args.lookback_days,
            max_documents=args.max_documents,
            output_dir=Path(args.output_dir),
        )
    if "news" in selected_sources:
        results["news"] = collect_news(tickers, limit=args.news_limit)
    if "reddit" in selected_sources:
        results["reddit"] = collect_reddit(
            subreddit=args.subreddit,
            limit=args.reddit_limit,
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="asx,news,reddit")
    parser.add_argument("--tickers", default=",".join(settings.SUPPORTED_TICKERS))
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--max-documents", type=int, default=3)
    parser.add_argument("--news-limit", type=int, default=10)
    parser.add_argument("--subreddit", default="ASX")
    parser.add_argument("--reddit-limit", type=int, default=10)
    parser.add_argument("--output-dir", default="/app/output")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(populate(parse_args())), indent=2, default=str))
