
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.database.connection import SessionLocal
from app.models.information_platform import InformationPlatform
from app.models.scrape_run import ScrapeRun
from app.models.ticker import Ticker

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PARSING_DIR = _BACKEND_DIR / "parsing"
for _path in (_BACKEND_DIR, _PARSING_DIR):
    path_text = str(_path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from parsing.pipeline import process_announcement  # noqa: E402
from scrapers.base import Announcement  # noqa: E402
from scrapers.registry import available_tickers, scrape  # noqa: E402


ASX_PLATFORM_NAME = "ASX"
ASX_PLATFORM_TYPE = "asx_announcements"
DEFAULT_OUTPUT_DIR = Path("/app/output")


class UnknownTickerError(ValueError):
    """Raised when no scraper is registered for the requested ticker."""


@dataclass(frozen=True)
class ScrapeOrchestrationResult:
    """Summary of one orchestrated ticker scrape."""

    scrape_run_id: UUID
    ticker: str
    status: str
    items_found: int
    items_saved: int
    errors: list[str] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_platform(db: Session) -> InformationPlatform:
    platform = (
        db.query(InformationPlatform)
        .filter(InformationPlatform.name == ASX_PLATFORM_NAME)
        .first()
    )
    if platform:
        return platform

    platform = InformationPlatform(
        name=ASX_PLATFORM_NAME,
        platform_type=ASX_PLATFORM_TYPE,
        scrape_enabled=True,
    )
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform


def _get_or_create_ticker(db: Session, ticker_symbol: str) -> Ticker:
    ticker = db.query(Ticker).filter(Ticker.symbol == ticker_symbol).first()
    if ticker:
        return ticker

    ticker = Ticker(
        symbol=ticker_symbol,
        company_name=ticker_symbol,
        exchange="ASX",
    )
    db.add(ticker)
    db.commit()
    db.refresh(ticker)
    return ticker


def _start_scrape_run(ticker_symbol: str) -> UUID:
    with SessionLocal() as db:
        platform = _get_or_create_platform(db)
        ticker = _get_or_create_ticker(db, ticker_symbol)
        scrape_run = ScrapeRun(
            platform_id=platform.id,
            ticker_id=ticker.id,
            status="running",
            started_at=_utcnow(),
            items_found=0,
            items_saved=0,
        )
        db.add(scrape_run)
        db.commit()
        db.refresh(scrape_run)
        return scrape_run.id


def _finish_scrape_run(
    scrape_run_id: UUID,
    *,
    status: str,
    items_found: int,
    items_saved: int,
    error_message: str | None = None,
) -> None:
    with SessionLocal() as db:
        scrape_run = (
            db.query(ScrapeRun)
            .filter(ScrapeRun.id == scrape_run_id)
            .first()
        )
        if not scrape_run:
            return

        scrape_run.status = status
        scrape_run.finished_at = _utcnow()
        scrape_run.items_found = items_found
        scrape_run.items_saved = items_saved
        scrape_run.error_message = error_message
        db.commit()


def _error_text(errors: list[str]) -> str | None:
    if not errors:
        return None
    return "\n".join(errors)[:8000]


def _process_downloaded_announcements(
    announcements: list[Announcement],
) -> tuple[int, list[str]]:
    items_saved = 0
    errors: list[str] = []

    for announcement in announcements:
        if not announcement.local_path:
            errors.append(
                f"{announcement.ticker}: no PDF downloaded for "
                f"'{announcement.title}'"
            )
            continue

        try:
            process_announcement(announcement)
            items_saved += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(
                f"{announcement.ticker}: failed to process "
                f"'{announcement.title}': {exc}"
            )

    return items_saved, errors


async def run_ticker_scrape(
    ticker_symbol: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> ScrapeOrchestrationResult:
    """
    Run the full ASX scrape pipeline for one registered ticker.

    The current storage layer does not report duplicates yet, so ``items_saved``
    means successfully processed announcements. Duplicate-aware counts are the
    next storage change.
    """
    ticker = ticker_symbol.upper()
    if ticker not in available_tickers():
        raise UnknownTickerError(
            f"No scraper implemented for '{ticker}'. Available: {available_tickers()}"
        )

    scrape_run_id = _start_scrape_run(ticker)
    items_found = 0
    items_saved = 0
    errors: list[str] = []

    try:
        announcements = await scrape(ticker, output_dir)
        items_found = len(announcements)
        items_saved, errors = _process_downloaded_announcements(announcements)
        status = "completed" if items_saved > 0 or not errors else "failed"
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        errors.append(f"{ticker}: scrape failed: {exc}")

    _finish_scrape_run(
        scrape_run_id,
        status=status,
        items_found=items_found,
        items_saved=items_saved,
        error_message=_error_text(errors),
    )

    return ScrapeOrchestrationResult(
        scrape_run_id=scrape_run_id,
        ticker=ticker,
        status=status,
        items_found=items_found,
        items_saved=items_saved,
        errors=errors,
    )
