"""BHP: market announcements on BHP's investor hub.

Discovery lists each announcement's article page. Resolving the article to
its PDF is download work, so Queue B carries the stable article URL and
discovery makes no document requests.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from app.services.title_normalization import normalise_title
from lambdas.common import PermanentDocumentError

from ..adapter import DocumentRequest, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render, SourceUnreachableError
from ..html import Element, parse_html
from ..parsing import DAY_MONTH_YEAR, ISO, SLASHED, first_date, unique

# BHP keeps some page resources open indefinitely; the committed HTML is
# enough for the links.
LISTING = Render(wait_until="commit", timeout_ms=30_000, settle_ms=3_000)
USEFUL_TERMS = (
    "market-announcements",
    "investor",
    "asx",
    "announcement",
    "results",
    "dividend",
    "operational review",
    "annual report",
    "quarterly",
)


def clean_bhp_title(raw_title: str, article_url: str) -> str:
    """Retain the BHP-specific entry point while using shared title cleanup."""
    return normalise_title(raw_title, article_url)


class BHPAdapter(SourceAdapter):
    hosts = frozenset({"www.bhp.com", "bhp.com"})

    async def _list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(disable_http2=True, ignore_https_errors=True) as web:
            try:
                page = await web.render(self.source_url, LISTING)
            except SourceUnreachableError:
                # Some Chromium/AWS networks fail BHP's HTTP/2 negotiation
                # even though the same public page works over HTTP/1.1.
                fetched = await web.get_page(
                    self.source_url, headers={"User-Agent": "Mozilla/5.0"}
                )
                page = Page(url=fetched.url, html=_without_scripts(fetched.html))
        return parse_listing(page, ticker=self.ticker, source_url=self.source_url)

    async def fetch_document(self, request: DocumentRequest, *, max_bytes: int):
        article_url = self._validated(request.document_url)
        async with self.fetcher.session(disable_http2=True) as web:
            article = await web.request_page(article_url)
            document_url = self._validated(article_pdf_url(Page(
                url=self._validated(article.url), html=article.html
            )))
            return await web.request_document(
                document_url,
                hosts=self.hosts,
                referer=article_url,
                max_bytes=max_bytes,
            )


def _without_scripts(html: str) -> str:
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)


def parse_listing(page: Page, *, ticker: str, source_url: str) -> list[Announcement]:
    announcements: list[Announcement] = []
    for link in parse_html(page.html).select("a[href]"):
        href = link.get("href")
        text = link.text.strip()
        if not href or not text:
            continue
        article_url = urljoin(source_url, href)
        title = clean_bhp_title(text, article_url)
        if not _looks_like_article(article_url, title):
            continue
        date = _nearby_date(link)
        if date is None:
            continue
        announcements.append(
            Announcement(
                ticker=ticker,
                title=title,
                date=date,
                pdf_url=article_url,
                source_url=source_url,
                metadata={"article_url": article_url, "source_id": article_url},
            )
        )
    return unique(announcements, key=lambda item: item.pdf_url)


def article_pdf_url(article: Page) -> str:
    """The document an article page links to."""
    absolute = re.search(r"""https?://[^"'<>\\\s]+\.pdf(?:\?[^"'<>\\\s]*)?""", article.html)
    if absolute:
        return absolute.group(0)
    relative = re.search(r"""["']([^"'<>]+\.pdf(?:\?[^"'<>]*)?)["']""", article.html)
    if relative:
        return urljoin(article.url, relative.group(1))
    raise PermanentDocumentError(
        "BHP article does not contain a supported document link",
        code="document_link_not_found",
    )


def _looks_like_article(url: str, text: str) -> bool:
    url_lower = url.lower()
    text_lower = text.lower()
    if "bhp.com" not in url_lower and url_lower.startswith("http"):
        return False
    return any(term in url_lower or term in text_lower for term in USEFUL_TERMS)


def _nearby_date(link: Element) -> datetime | None:
    container = link.closest("article, li, .card, .search-result, .result, div")
    if container is None:
        return None
    return first_date(
        container.text,
        (rf"\b{DAY_MONTH_YEAR}\b", rf"\b{SLASHED}\b", rf"\b{ISO}\b"),
        ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"),
    )
