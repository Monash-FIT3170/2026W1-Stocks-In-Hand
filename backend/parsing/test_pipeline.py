"""
Full pipeline integration test: scrape → classify/extract → store.

Run in Docker (from spike/ directory):
    docker compose up --build backend

    docker compose exec backend python parsing/test_pipeline.py

Optionally pass a ticker (default: ANZ):
    docker compose exec backend python parsing/test_pipeline.py CSL
"""
import asyncio
import os
import platform
import pprint
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import env
env.load_env()

from scrapers.registry import scrape
from pipeline import process_announcement

TICKER = sys.argv[1].upper() if len(sys.argv) > 1 else "ANZ"
OUTPUT_DIR = Path(__file__).parents[1 if platform.system() != "Windows" else 2] / "output"


async def main() -> None:
    print(f"[1/3] Scraping {TICKER}...")
    announcements = await scrape(TICKER, OUTPUT_DIR)
    print(f"      {len(announcements)} announcements downloaded\n")

    print("[2/3] Classifying, extracting, and storing...\n")
    for ann in announcements:
        report = process_announcement(ann)
        category_name = report.category.name if report.category else "UNKNOWN"
        print(f"  {ann.title[:60]}")
        print(f"    category={category_name}  confidence={report.confidence:.2f}  method={report.method}")
        # if report.extracted_data:
        #     pprint.pprint(report.extracted_data, indent=6, width=100, sort_dicts=False)
        print()

    print(f"[3/3] Done. {len(announcements)} announcements processed.")


asyncio.run(main())
