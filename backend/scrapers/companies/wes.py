"""Wesfarmers (WES): the ASX announcements list on its investor centre.

Wesfarmers serves a document only to a browser that clicks its link on the
listing page, so download reopens the listing and clicks the same link.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

from lambdas.common import PermanentDocumentError

from ..adapter import DocumentRequest, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render
from ..html import Element, parse_html

ROWS = "article.asx-announce div.asx-results li"
LISTING = Render(wait_for=ROWS, wait_for_timeout_ms=15_000, required=True)


class WESAdapter(SourceAdapter):
    hosts = frozenset({"www.wesfarmers.com.au", "wesfarmers.com.au"})

    async def list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(ignore_https_errors=True) as web:
            page = await web.render(self.source_url, LISTING)
        return parse_listing(page, ticker=self.ticker, source_url=self.source_url)

    async def fetch_document(self, request: DocumentRequest, *, max_bytes: int):
        source_url = self._validated(self.source_url)
        expected_url = self._validated(request.document_url)
        async with self.fetcher.session(disable_http2=True) as web:
            page = await web.render(source_url, LISTING)
            self._validated(page.url)
            href = matching_link(
                page,
                source_url=source_url,
                document_url=expected_url,
                raw_href=request.metadata.get("raw_href"),
                title=request.title,
            )
            if href is None:
                raise PermanentDocumentError(
                    "Wesfarmers document link is no longer listed",
                    code="document_link_not_found",
                )
            return await web.click_download(
                source_url,
                wait_for=ROWS,
                link_selector=f'{ROWS} a[href="{_css_string(href)}"]',
                hosts=self.hosts,
                max_bytes=max_bytes,
            )


def parse_listing(page: Page, *, ticker: str, source_url: str) -> list[Announcement]:
    announcements: list[Announcement] = []
    for row in parse_html(page.html).select(ROWS):
        date_element = row.select_one("span.date-time")
        link = row.select_one("a[href]")
        if date_element is None or link is None:
            continue
        date_text = date_element.text.strip()
        title = link.text.strip()
        href = link.get("href")
        if not date_text or not title or not href:
            continue
        try:
            date = datetime.strptime(date_text, "%d.%m.%y")
        except ValueError:
            continue
        announcements.append(
            Announcement(
                ticker=ticker,
                title=title,
                date=date,
                pdf_url=href if href.startswith("http") else urljoin(source_url, href),
                source_url=source_url,
                metadata={"raw_href": href, "raw_date": date_text, "source_id": href},
            )
        )
    return announcements


def matching_link(
    page: Page,
    *,
    source_url: str,
    document_url: str,
    raw_href: object,
    title: str | None,
) -> str | None:
    """The href of the listed link that names this document, if it is still listed."""
    for row in parse_html(page.html).select(ROWS):
        link: Element | None = row.select_one("a[href]")
        if link is None:
            continue
        href = link.get("href") or ""
        if (
            urljoin(source_url, href) == document_url
            or (isinstance(raw_href, str) and href == raw_href)
            or (title and link.text.strip() == title)
        ):
            return href
    return None


def _css_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
