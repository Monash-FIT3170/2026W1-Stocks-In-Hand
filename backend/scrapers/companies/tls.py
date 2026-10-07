"""Telstra (TLS): the Miraqle announcements table framed on its announcements page."""

from __future__ import annotations

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render
from ..miraqle import parse_table

# Telstra frames its ASX table from events.miraqle.com.
LISTING = Render(settle_ms=3_000, frame_url_contains=("events.miraqle.com", "iFrames"))


class TLSAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset({"www.telstra.com.au", "telstra.com.au", "events.miraqle.com"})

    async def _list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(ignore_https_errors=True) as web:
            frame = await web.render(self.source_url, LISTING)
        return parse_feed_frame(frame, ticker=self.ticker, source_url=self.source_url)


def parse_feed_frame(frame: Page, *, ticker: str, source_url: str) -> list[Announcement]:
    return parse_table(
        frame,
        ticker=ticker,
        listing_url=source_url,
        hosts=TLSAdapter.hosts,
        row_selector="tr, li, article, section, div",
        framed=True,
    )
