"""
CLI tool for manually testing the ASX source adapters.

INSTRUCTIONS TO RUN:

- Make sure you are in the backend directory
- Then run with docker


> cd backend
> docker compose exec backend python test_scrapers.py

Each chosen company's adapter lists its documents, as discovery does, and
downloads each one, as the download worker does. Documents save to the output
folder for that specific company.

"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.sources import SOURCES
from cli_config import OUTPUT_DIR
from scrapers.adapter import DocumentRequest
from scrapers.base import Announcement
from scrapers.registry import adapter_for, discover

SEP = "-" * 60


def show_menu(tickers: list[str]) -> None:
    print(f"\n{SEP}")
    print("  ASX Scraper Test Tool")
    print(SEP)
    for i, ticker in enumerate(tickers, 1):
        print(f"  {i}. {ticker}")
    print(f"  A. All")
    print(f"  Q. Quit")
    print(SEP)


def get_selection(tickers: list[str]) -> list[str]:
    while True:
        raw = input("Select scrapers to run (e.g. 1, 2 or A): ").strip().upper()

        if raw == "Q":
            print("Exiting.")
            sys.exit(0)

        if raw == "A":
            return tickers

        selected = []
        valid = True
        for part in raw.replace(",", " ").split():
            if not part.isdigit() or not (1 <= int(part) <= len(tickers)):
                print(f"  Invalid selection: '{part}'. Enter numbers 1-{len(tickers)}, A, or Q.")
                valid = False
                break
            ticker = tickers[int(part) - 1]
            if ticker not in selected:
                selected.append(ticker)

        if valid and selected:
            return selected


def print_results(ticker: str, announcements: list, elapsed: float) -> None:
    print(f"\n{SEP}")
    print(f"  {ticker}  —  {len(announcements)} announcement(s)  ({elapsed:.1f}s)")
    print(SEP)
    for ann in announcements:
        date_str = ann.date.strftime("%Y-%m-%d")
        title = ann.title[:58] + ".." if len(ann.title) > 60 else ann.title
        path = str(ann.local_path) if ann.local_path else "not downloaded"
        print(f"  {date_str}  {title}")
        print(f"           {path}")
    print(SEP)


async def download(announcement: Announcement, directory: Path) -> Path:
    """Fetch one listed document through its adapter and save it in ``directory``."""
    downloaded = await adapter_for(announcement.ticker).fetch_document(
        DocumentRequest(
            document_url=announcement.pdf_url,
            title=announcement.title,
            metadata=announcement.metadata,
        ),
        max_bytes=settings.MAX_DOCUMENT_BYTES,
    )
    clean_title = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in announcement.title
    ).strip("_")[:120] or "announcement"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{announcement.date:%Y-%m-%d}_{clean_title}.{downloaded.extension}"
    path.write_bytes(downloaded.content)
    return path


async def scrape(ticker: str, output_dir: Path) -> list[Announcement]:
    """List a company's documents and save each one in ``output_dir/<ticker>``."""
    announcements = await discover(ticker)
    for announcement in announcements:
        announcement.local_path = await download(announcement, output_dir / ticker)
    return announcements


async def run_scraper(ticker: str) -> None:
    print(f"\nRunning {ticker} scraper...")
    start = time.monotonic()
    try:
        results = await scrape(ticker, OUTPUT_DIR)
        elapsed = time.monotonic() - start
        print_results(ticker, results, elapsed)
    except Exception as exc:
        elapsed = time.monotonic() - start
        print(f"\n  ERROR running {ticker} ({elapsed:.1f}s): {exc}")


async def main() -> None:
    tickers = list(SOURCES)
    if not tickers:
        print("No scrapers registered.")
        return

    show_menu(tickers)
    selected = get_selection(tickers)

    for ticker in selected:
        await run_scraper(ticker)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
