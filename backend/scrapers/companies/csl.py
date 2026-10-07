"""CSL: the ASX announcements list on CSL's investor site."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin, urlsplit

from ..adapter import DocumentRequest, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render
from ..html import parse_html

LISTING = Render(wait_for="div.list-item", wait_for_timeout_ms=30_000, required=True)


class CSLAdapter(SourceAdapter):
    # CSL's PDFs can redirect to the ASX's own announcement hosts.
    hosts = frozenset(
        {"investors.csl.com", "announcements.asx.com.au", "wcsecure.weblink.com.au"}
    )

    async def list_documents(self) -> list[Announcement]:
        async with self.fetcher.session() as web:
            page = await web.render(self.source_url, LISTING)
        return parse_listing(page, ticker=self.ticker, source_url=self.source_url)

    async def fetch_document(self, request: DocumentRequest, *, max_bytes: int):
        async with self.fetcher.session() as web:
            return await web.download(
                self._validated(request.document_url),
                hosts=self.hosts,
                referer="https://investors.csl.com/",
                max_bytes=max_bytes,
            )


def parse_listing(page: Page, *, ticker: str, source_url: str) -> list[Announcement]:
    announcements: list[Announcement] = []
    for item in parse_html(page.html).select("div.list-item"):
        date_element = item.select_one("div.list-date")
        link = item.select_one("a.asx-document")
        if date_element is None or link is None:
            continue
        title = link.text.strip()
        href = link.get("href")
        if not title or not href:
            continue
        date = _parse_date(date_element.text.strip())
        if date is None:
            continue
        document_url = urljoin(source_url, href)
        if urlsplit(document_url).scheme not in {"http", "https"}:
            continue
        announcements.append(
            Announcement(
                ticker=ticker,
                title=title,
                date=date,
                pdf_url=document_url,
                source_url=source_url,
            )
        )
    return announcements


def _parse_date(value: str) -> datetime | None:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
