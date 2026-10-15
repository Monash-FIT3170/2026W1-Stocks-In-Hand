"""Coles (COL): the Miraqle announcements table on Coles Group's investor page."""

from __future__ import annotations

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render
from ..miraqle import parse_table

LISTING = Render(settle_ms=2_500)


class COLAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset({"www.colesgroup.com.au", "colesgroup.com.au"})

    async def _list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(ignore_https_errors=True) as web:
            page = await web.render(self.source_url, LISTING)
        return parse_listing(page, ticker=self.ticker, source_url=self.source_url)


def parse_listing(page: Page, *, ticker: str, source_url: str) -> list[Announcement]:
    return parse_table(
        page,
        ticker=ticker,
        listing_url=source_url,
        hosts=COLAdapter.hosts,
        row_selector="tr, li, div, section",
    )
