"""Record what source adapters fetch from the live sites, as test fixtures.

    python -m tools.record_source_pages CSL WES ...   # from backend/

Each adapter's list_documents runs against the live web through a
RecordingFetcher, which saves every page and feed into
tests/fixtures/sources/<adapter>/ (style and SVG are dropped to keep the
files small). The adapter tests replay these recordings, so re-record when
a site changes layout and update the expectations the tests pin.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.sources import SOURCES, normalise_symbol  # noqa: E402
from scrapers.fetching import RecordingFetcher  # noqa: E402
from scrapers.registry import ADAPTER_TYPES  # noqa: E402

FIXTURES = BACKEND / "tests" / "fixtures" / "sources"


async def record(ticker: str) -> list[dict]:
    source = SOURCES[normalise_symbol(ticker)]
    directory = FIXTURES / source.adapter
    shutil.rmtree(directory, ignore_errors=True)
    adapter = ADAPTER_TYPES[source.adapter](source, RecordingFetcher(directory))
    listed = await adapter.list_documents()
    return [
        {
            "title": item.title,
            "date": item.date.isoformat(),
            "pdf_url": item.pdf_url,
            "source_url": item.source_url,
            "metadata": item.metadata,
        }
        for item in listed
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="+")
    args = parser.parse_args()
    for ticker in args.tickers:
        listed = asyncio.run(record(ticker))
        print(json.dumps({"ticker": ticker, "listed": listed}, indent=1, default=str))


if __name__ == "__main__":
    main()
