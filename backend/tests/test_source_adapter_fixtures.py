"""Each browser-based source adapter, replayed from its recorded pages.

``python -m tools.record_source_pages <TICKER>`` recorded these pages from
the live sites on 2026-10-07. The listed documents matched the previous
scrapers' output on the live sites the same day, item for item. A
document's identity is its source ID or else its document URL, so the
pinned URLs must not change, or stored documents would be discovered again.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.sources import SOURCES
from lambdas.common import PermanentDocumentError
from scrapers.adapter import DocumentRequest
from scrapers.companies.wes import ROWS
from scrapers.fetching import Page, RecordedFetcher, request_key
from scrapers.registry import ADAPTER_TYPES

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
RECORDED_ON = datetime(2026, 10, 7)
PDF = b"%PDF-1.7\nannouncement"


def _adapter(ticker: str, *, answers: dict | None = None, recorded: bool = True):
    source = SOURCES[ticker]
    fetcher = RecordedFetcher(
        FIXTURES / source.adapter if recorded else None,
        answers=answers,
    )
    adapter = ADAPTER_TYPES[source.adapter](source, fetcher, clock=lambda: RECORDED_ON)
    return adapter, fetcher


def _listed(ticker: str):
    adapter, _fetcher = _adapter(ticker)
    return adapter, asyncio.run(adapter.list_documents())


EXPECTED = {
    "CSL": (
        10,
        {
            "title": "CSL prices US$1.5 billion in Corporate Bonds",
            "date": datetime(2026, 10, 7),
            "pdf_url": (
                "https://investors.csl.com/pdf/e9774456-f57a-4906-bde8-bca48b11fdaa/"
                "Platform/ListPage/CSL-prices-US15-billion-in-Corporate-Bonds.pdf"
            ),
            "metadata": {},
        },
    ),
    "WES": (
        33,
        {
            "title": "Update - Dividend/Distribution - WES 17 KB",
            "date": datetime(2026, 9, 30),
            "pdf_url": (
                "https://www.wesfarmers.com.au/docs/default-source/asx-announcements/"
                "update-dividend-distribution-wes-20260930023559.pdf?sfvrsn=963eafbb_0"
            ),
            "metadata": {
                "raw_href": (
                    "https://www.wesfarmers.com.au/docs/default-source/asx-announcements/"
                    "update-dividend-distribution-wes-20260930023559.pdf?sfvrsn=963eafbb_0"
                ),
                "raw_date": "30.09.26",
                "source_id": (
                    "https://www.wesfarmers.com.au/docs/default-source/asx-announcements/"
                    "update-dividend-distribution-wes-20260930023559.pdf?sfvrsn=963eafbb_0"
                ),
            },
        },
    ),
    "COL": (
        20,
        {
            "title": "Change of Director's Interest Notice - J Chow",
            "date": datetime(2026, 9, 29),
            "pdf_url": (
                "https://www.colesgroup.com.au/DownloadFile.axd"
                "?file=/Report/ComNews/20260929/03141278.pdf"
            ),
            "metadata": {
                "listing_url": "https://www.colesgroup.com.au/investors/?page=asx-announcements",
                "raw_date": "29 September 2026",
            },
        },
    ),
    "COH": (
        40,
        {
            "title": "Change in substantial holding",
            "date": datetime(2026, 10, 6),
            "pdf_url": (
                "https://coh.live.irmau.com/irm/pdf/1d5cd744-a724-4e99-a22a-4c68344ebd26/"
                "Platform/ListPage/Change-in-substantial-holding.pdf"
            ),
            "metadata": {
                "listing_url": SOURCES["COH"].source_url,
                "feed_url": (
                    "https://coh.live.irmau.com/irm/ShowCategory.aspx"
                    "?CategoryId=8&FilterStyle=B&archive=true&year=2026"
                ),
                "raw_date": "6-Oct-2026",
                "year": "2026",
            },
        },
    ),
    "TLS": (
        20,
        {
            "title": "Update - Notification of buy-back - TLS",
            "date": datetime(2026, 10, 6),
            "pdf_url": (
                "https://events.miraqle.com/DownloadFile.axd"
                "?file=/Report/ComNews/20261006/03145040.pdf"
            ),
            "metadata": {
                "listing_url": SOURCES["TLS"].source_url,
                "feed_url": "https://events.miraqle.com/TLS-Feed/iFrames/?page=news",
                "raw_date": "06 October 2026",
            },
        },
    ),
    "MQG": (
        10,
        {
            "title": "31 March 2026\nMFL 2026 full-year result - annual report\nPDF\n2 MB",
            "date": datetime(2026, 3, 31),
            "pdf_url": (
                "https://www.macquarie.com/assets/macq/investor/reports/2026/"
                "mfl-financial-statements-march-26-signed-financials.pdf"
            ),
            "metadata": {
                "listing_url": SOURCES["MQG"].source_url,
                "article_url": (
                    "https://www.macquarie.com/assets/macq/investor/reports/2026/"
                    "mfl-financial-statements-march-26-signed-financials.pdf"
                ),
                "raw_date": "2026-03-31T00:00:00",
            },
        },
    ),
    "ORG": (
        10,
        {
            "title": "Full Year Results 2026",
            "date": datetime(2026, 8, 13, 8, 33, 41),
            "pdf_url": (
                "https://www.originenergy.com.au/wp-content/uploads/285/"
                "Origin-Energy-FY26-ASX-Media-Release.pdf"
            ),
            "metadata": {
                "listing_url": SOURCES["ORG"].source_url,
                "article_url": (
                    "https://www.originenergy.com.au/about/investors-media/"
                    "full-year-results-2026/"
                ),
                "raw_date": "2026-08-13T08:33:41",
            },
        },
    ),
    "RIO": (
        10,
        {
            "title": "Becoming a substantial holder",
            "date": datetime(2026, 10, 7),
            "pdf_url": (
                "https://ne-cdn.eurolandir.com/press-releases-attachments./4192109/"
                "Becoming_a_substantial_holder_07102026081815.pdf"
            ),
            "metadata": {
                "listing_url": (
                    "https://tools.eurolandir.com/tools/pressreleases/"
                    "?companycode=uk-rio&v=asx2023&lang=en-GB"
                ),
                "article_url": (
                    "https://tools.eurolandir.com/tools/Pressreleases/GetPressRelease/"
                    "?ID=8153715&lang=en-GB&companycode=uk-rio&v=asx2023"
                ),
                "raw_date": "2026-10-07T00:00:00",
            },
        },
    ),
    "WDS": (
        17,
        {
            "title": "Address to Leadership Matters WA by CEO and Managing Director Liz Westcott",
            "date": datetime(2026, 10, 1),
            "pdf_url": (
                "https://www.woodside.com/docs/default-source/media-releases/"
                "address-to-leadership-matters-wa-by-ceo-and-managing-director-liz-westcott.pdf"
                "?sfvrsn=c432f0d8_1"
            ),
            "metadata": {
                "listing_url": SOURCES["WDS"].source_url,
                "article_url": (
                    "https://www.woodside.com/docs/default-source/media-releases/"
                    "address-to-leadership-matters-wa-by-ceo-and-managing-director-liz-westcott.pdf"
                    "?sfvrsn=c432f0d8_1"
                ),
                "raw_date": "2026-10-01T00:00:00",
            },
        },
    ),
}


@pytest.mark.parametrize("ticker", sorted(EXPECTED))
def test_recorded_pages_list_the_same_documents(ticker: str) -> None:
    count, first = EXPECTED[ticker]

    adapter, listed = _listed(ticker)

    assert len(listed) == count
    assert {
        "title": listed[0].title,
        "date": listed[0].date,
        "pdf_url": listed[0].pdf_url,
        "metadata": listed[0].metadata,
    } == first
    assert all(item.ticker == ticker for item in listed)
    assert all(urlsplit(item.pdf_url).hostname in adapter.hosts for item in listed)
    assert len({item.pdf_url for item in listed}) == len(listed)


@pytest.mark.parametrize("ticker", ["COH", "COL", "MQG", "ORG", "RIO", "TLS", "WDS"])
def test_download_seeds_a_browser_session_from_the_listing(ticker: str) -> None:
    _adapter_listed, listed = _listed(ticker)
    item = listed[0]
    seed = item.metadata.get("feed_url") or item.metadata["listing_url"]
    adapter, fetcher = _adapter(
        ticker,
        answers={request_key("REQUEST-DOCUMENT", item.pdf_url): PDF},
        recorded=False,
    )

    document = asyncio.run(
        adapter.fetch_document(
            DocumentRequest(item.pdf_url, item.title, item.metadata),
            max_bytes=1024,
        )
    )

    assert document.content == PDF
    assert fetcher.requests == [
        {
            "method": "REQUEST-DOCUMENT",
            "url": item.pdf_url,
            "referer": seed,
            "seed_url": seed,
        }
    ]


def test_csl_downloads_over_plain_http() -> None:
    _csl, listed = _listed("CSL")
    url = listed[0].pdf_url
    adapter, fetcher = _adapter(
        "CSL", answers={request_key("DOWNLOAD", url): PDF}, recorded=False
    )

    document = asyncio.run(adapter.fetch_document(DocumentRequest(url), max_bytes=1024))

    assert document.content == PDF
    assert fetcher.requests[0]["referer"] == "https://investors.csl.com/"


def test_wes_clicks_the_listed_link_to_download() -> None:
    _wes, listed = _listed("WES")
    item = listed[0]
    listing = (FIXTURES / "wes").glob("*.html")
    page = Page(url=SOURCES["WES"].source_url, html=next(listing).read_text())
    adapter, fetcher = _adapter(
        "WES",
        answers={
            request_key("RENDER", SOURCES["WES"].source_url): page,
            request_key("CLICK", SOURCES["WES"].source_url): PDF,
        },
        recorded=False,
    )

    document = asyncio.run(
        adapter.fetch_document(
            DocumentRequest(item.pdf_url, item.title, item.metadata), max_bytes=1024
        )
    )

    assert document.content == PDF
    assert fetcher.requests[-1]["link_selector"] == (
        f'{ROWS} a[href="{item.metadata["raw_href"]}"]'
    )


def test_wes_reports_a_document_that_is_no_longer_listed() -> None:
    adapter, _fetcher = _adapter(
        "WES",
        answers={
            request_key("RENDER", SOURCES["WES"].source_url): Page(
                url=SOURCES["WES"].source_url, html="<article class='asx-announce'></article>"
            )
        },
        recorded=False,
    )

    with pytest.raises(PermanentDocumentError) as error:
        asyncio.run(
            adapter.fetch_document(
                DocumentRequest(
                    "https://www.wesfarmers.com.au/docs/default-source/gone.pdf",
                    "Gone",
                ),
                max_bytes=1024,
            )
        )

    assert error.value.code == "document_link_not_found"


BHP_LISTING = """
<div class="result"><span>20 January 2026</span>
<a href="/news/media-centre/releases/2026/01/bhp-operational-review">
EXCHANGE RELEASES 20 January 2026 BHP Operational Review for the half year</a></div>
<div class="result"><a href="/careers">Careers</a></div>
<div class="result"><a href="/investor-hub/annual-report">Annual report</a></div>
"""


def test_bhp_lists_dated_article_pages_by_url() -> None:
    adapter, _fetcher = _adapter(
        "BHP",
        answers={
            request_key("RENDER", SOURCES["BHP"].source_url): Page(
                url=SOURCES["BHP"].source_url, html=BHP_LISTING
            )
        },
        recorded=False,
    )

    [listed] = asyncio.run(adapter.list_documents())

    article = "https://www.bhp.com/news/media-centre/releases/2026/01/bhp-operational-review"
    assert listed.pdf_url == article
    assert listed.date == datetime(2026, 1, 20)
    assert listed.metadata == {"article_url": article, "source_id": article}


def test_bhp_downloads_the_pdf_its_article_links() -> None:
    article = "https://www.bhp.com/news/media-centre/releases/2026/01/bhp-operational-review"
    pdf = "https://www.bhp.com/-/media/documents/media/reports-and-presentations/2026/review.pdf"
    adapter, fetcher = _adapter(
        "BHP",
        answers={
            request_key("REQUEST", article): Page(
                url=article, html=f'<a class="download" href="{pdf}">Download</a>'
            ),
            request_key("REQUEST-DOCUMENT", pdf): PDF,
        },
        recorded=False,
    )

    document = asyncio.run(adapter.fetch_document(DocumentRequest(article), max_bytes=1024))

    assert document.content == PDF
    assert fetcher.requests[-1]["referer"] == article


def test_bhp_article_without_a_document_is_permanent() -> None:
    article = "https://www.bhp.com/news/releases/no-attachment"
    adapter, _fetcher = _adapter(
        "BHP",
        answers={request_key("REQUEST", article): Page(url=article, html="<p>None</p>")},
        recorded=False,
    )

    with pytest.raises(PermanentDocumentError) as error:
        asyncio.run(adapter.fetch_document(DocumentRequest(article), max_bytes=1024))

    assert error.value.code == "document_link_not_found"


def test_bhp_listing_recorded_from_a_blocked_network_lists_nothing() -> None:
    # BHP answered this network with an Akamai "Access Denied" page.
    assert _listed("BHP")[1] == []
