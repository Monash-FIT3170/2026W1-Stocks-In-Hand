"""The manual scraper CLI, ``backend/test_scrapers.py``, over CSL's recorded pages.

Only a person runs the CLI, so this keeps it working with the source adapter
registry: scraping a ticker lists its documents through the ticker's adapter
and saves each one in the ticker's output folder.
"""

import asyncio
from pathlib import Path

import pytest

import test_scrapers
from app.sources import SOURCES
from scrapers import registry
from scrapers.fetching import RecordedFetcher, request_key
from scrapers.registry import ADAPTER_TYPES

RECORDED = Path(__file__).parent / "fixtures" / "sources" / "csl"
PDF = b"%PDF-1.7\nannouncement"


def test_scraping_a_ticker_saves_each_document_its_adapter_lists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    csl = SOURCES["CSL"]
    listed = asyncio.run(ADAPTER_TYPES["csl"](csl, RecordedFetcher(RECORDED)).list_documents())
    documents = {request_key("DOWNLOAD", item.pdf_url): PDF for item in listed}
    adapter = ADAPTER_TYPES["csl"](csl, RecordedFetcher(RECORDED, answers=documents))
    monkeypatch.setitem(registry.ADAPTERS, "csl", adapter)

    scraped = asyncio.run(test_scrapers.scrape("CSL", tmp_path))

    assert [item.pdf_url for item in scraped] == [item.pdf_url for item in listed]
    assert {item.local_path.parent for item in scraped} == {tmp_path / "CSL"}
    assert all(item.local_path.read_bytes() == PDF for item in scraped)
