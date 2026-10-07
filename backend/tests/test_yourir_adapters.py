"""ANZ, CBA and TCL list and fetch through their recorded YourIR feeds.

The feeds were recorded from the live sites on 2026-10-07. The document
identities (source IDs, or the document URL when there is none) must not
change, or stored documents would be discovered again as new ones.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.sources import SOURCES
from lambdas.common import PermanentDocumentError
from scrapers.adapter import DocumentRequest
from scrapers.companies.anz import ANZAdapter
from scrapers.companies.cba import CBAAdapter
from scrapers.companies.tcl import TCLAdapter
from scrapers.fetching import RecordedFetcher

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
PDF = b"%PDF-1.7\nannouncement"


def _feed(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}-yourir-feed.json").read_text())


def _adapter(adapter_type, ticker: str, responses: dict) -> tuple:
    fetcher = RecordedFetcher(responses)
    return adapter_type(SOURCES[ticker], fetcher), fetcher


def _listed(adapter_type, ticker: str, name: str):
    feed_url = adapter_type.feed.feed_url
    adapter, fetcher = _adapter(adapter_type, ticker, {feed_url: _feed(name)})
    return asyncio.run(adapter.list_documents()), fetcher.requests[0]


def test_anz_lists_its_feed_with_stable_identities() -> None:
    listed, request = _listed(ANZAdapter, "ANZ", "anz")

    assert len(listed) == 20
    first = listed[0]
    assert first.ticker == "ANZ"
    assert first.title == "Shareholder resolutions for consideration at ANZ's 2026 AGM"
    assert first.date == datetime(2026, 10, 5, 6, 37, 16, tzinfo=timezone.utc)
    assert first.metadata == {"yourir_id": "3A703331", "source_id": "3A703331"}
    assert first.pdf_url == (
        "https://yourir.info/resources/4d216b570d08af30/announcements/anz.asx/"
        "3A703331/ANZ_Shareholder_resolutions_for_consideration_at_ANZs_2026_AGM.pdf"
    )
    assert request["headers"] == {"Referer": "https://www.anz.com/"}
    assert request["params"]["appID"] == "4d216b570d08af30"
    assert request["params"]["includeOtherIssuers"] == 0
    assert request["params"]["pageSize"] == 20


def test_cba_lists_other_issuers_with_its_qualified_identities() -> None:
    listed, request = _listed(CBAAdapter, "CBA", "cba")

    assert len(listed) == 12
    first = listed[0]
    assert first.title == "Becoming a substantial holder for CAR"
    assert first.metadata == {
        "yourir_id": "cba.asx/2A1702632",
        "source_id": "cba.asx/2A1702632",
    }
    assert first.pdf_url == (
        "https://yourir.info/resources/e381e7bfa5abbe55/announcements/cba.asx/"
        "2A1702632/CBA_Becoming_a_substantial_holder_for_CAR.pdf"
    )
    assert request["headers"] == {"Referer": "https://www.commbank.com.au/"}
    assert request["params"]["includeOtherIssuers"] == 1
    assert request["params"]["pageSize"] == 12


def test_tcl_lists_feed_documents_identified_by_their_url() -> None:
    listed, request = _listed(TCLAdapter, "TCL", "tcl")

    assert len(listed) == 15
    first = listed[0]
    assert first.title == "Appendix 3Y - Change of Director's Interest Notice"
    assert first.pdf_url == (
        "https://yourir.info/api/v5/symbols/tcl.asx/announcements/3A703481/document"
    )
    assert first.metadata == {
        "listing_url": SOURCES["TCL"].source_url,
        "file_id": "3A703481",
        "api_symbol": "tcl.asx",
        "raw_time": "2026-10-07 08:50:39",
    }
    assert "source_id" not in first.metadata
    assert request["params"]["pageSize"] == 15


def test_feed_entries_without_an_id_heading_or_time_are_skipped() -> None:
    feed = {
        "items": {
            "fileID": ["A1", "", "A3", "A1"],
            "heading": ["  Results   day ", "No id", "No time", "Repeat"],
            "timestamp": [1791182236, 1791182236, None, 1791182236],
            "time": ["2026-10-05 17:37:16"] * 4,
        }
    }
    adapter, _fetcher = _adapter(ANZAdapter, "ANZ", {ANZAdapter.feed.feed_url: feed})

    [only] = asyncio.run(adapter.list_documents())

    assert only.title == "Results day"
    assert only.metadata["source_id"] == "A1"


def test_a_feed_without_its_item_arrays_is_rejected() -> None:
    adapter, _fetcher = _adapter(
        ANZAdapter,
        "ANZ",
        {ANZAdapter.feed.feed_url: {"items": {"heading": ["Results"]}}},
    )

    with pytest.raises(ValueError, match="invalid item schema"):
        asyncio.run(adapter.list_documents())


def _fetch(adapter, request: DocumentRequest):
    return asyncio.run(adapter.fetch_document(request, max_bytes=1024))


def test_anz_fetches_the_resource_with_its_page_as_referer() -> None:
    url = "https://yourir.info/resources/4d216b570d08af30/announcements/anz.asx/3A1/ANZ_Results.pdf"
    adapter, fetcher = _adapter(ANZAdapter, "ANZ", {url: PDF})

    document = _fetch(adapter, DocumentRequest(url, metadata={"yourir_id": "3A1"}))

    assert document.content == PDF
    assert fetcher.requests == [{"url": url, "referer": SOURCES["ANZ"].source_url}]


@pytest.mark.parametrize(
    ("adapter_type", "ticker", "yourir_id", "fallback"),
    [
        (
            ANZAdapter,
            "ANZ",
            "3A1",
            "https://yourir.info/resources/4d216b570d08af30/announcements/3A1/announcement.pdf",
        ),
        (
            CBAAdapter,
            "CBA",
            "cba.asx/2A1",
            "https://yourir.info/resources/e381e7bfa5abbe55/announcements/cba.asx/2A1/announcement.pdf",
        ),
    ],
)
def test_a_missing_resource_falls_back_to_its_fixed_file_name(
    adapter_type,
    ticker: str,
    yourir_id: str,
    fallback: str,
) -> None:
    url = f"{adapter_type.feed.resources_url}/renamed.pdf"
    missing = PermanentDocumentError("Document no longer exists", code="document_not_found")
    adapter, _fetcher = _adapter(adapter_type, ticker, {url: missing, fallback: PDF})

    document = _fetch(adapter, DocumentRequest(url, metadata={"yourir_id": yourir_id}))

    assert document.final_url == fallback


def test_a_rejected_resource_does_not_fall_back() -> None:
    url = "https://yourir.info/resources/4d216b570d08af30/announcements/anz.asx/3A1/x.pdf"
    rejected = PermanentDocumentError("Rejected", code="document_rejected")
    adapter, fetcher = _adapter(ANZAdapter, "ANZ", {url: rejected})

    with pytest.raises(PermanentDocumentError):
        _fetch(adapter, DocumentRequest(url, metadata={"yourir_id": "3A1"}))

    assert len(fetcher.requests) == 1


def test_tcl_fetches_the_feed_document_for_its_app() -> None:
    url = "https://yourir.info/api/v5/symbols/tcl.asx/announcements/3A703481/document"
    requested = f"{url}?appID=a50955429d255a58&liveness=live"
    adapter, fetcher = _adapter(TCLAdapter, "TCL", {requested: PDF})

    document = _fetch(adapter, DocumentRequest(url))

    assert document.content == PDF
    assert fetcher.requests[0]["referer"] == SOURCES["TCL"].source_url
