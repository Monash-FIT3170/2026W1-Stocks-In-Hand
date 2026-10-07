"""Macquarie Group (MQG): the investor Reports page.

Macquarie does not mirror its routine ASX announcement feed; its investor
hub links to the ASX's own company page for that. This adapter covers the
Reports page (annual and half-year financial reports). The page is built
client-side by an Adobe Experience Manager filter widget. Each report
resolves to a detail page at /investors/reports/<slug>.html, which links to
the PDF, often several times with different #page= fragments; fragments are
dropped because they never reach the server.
"""

from __future__ import annotations

import re

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..article_listings import (
    MONTH_FIRST_DATES,
    ArticleLink,
    article_pdf_url,
    dated_links,
    resolved_announcements,
)
from ..base import Announcement
from ..fetching import Page, Render

LISTING = Render(
    wait_until="networkidle",
    wait_for="a[href*='/investors/reports/'], a[href*='.pdf']",
    settle_ms=1_000,
)
ARTICLE = Render(settle_ms=1_000)


class MQGAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset({"www.macquarie.com", "macquarie.com"})

    async def _list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(ignore_https_errors=True) as web:
            listing = await web.render(self.source_url, LISTING)

            async def pdf_url_for(link: ArticleLink) -> str | None:
                without_fragment = link.article_url.split("#", 1)[0]
                if without_fragment.lower().split("?", 1)[0].endswith(".pdf"):
                    return without_fragment
                article = await web.render(link.article_url, ARTICLE)
                return article_pdf_url(article, link.article_url, drop_fragment=True)

            return await resolved_announcements(
                report_links(listing, listing_url=self.source_url),
                pdf_url_for,
                ticker=self.ticker,
                listing_url=self.source_url,
            )


def report_links(listing: Page, *, listing_url: str) -> list[ArticleLink]:
    return dated_links(
        listing, base_url=listing_url, rules=MONTH_FIRST_DATES, title_for=_report_title
    )


def _report_title(url: str, text: str) -> str | None:
    if not text:
        return None
    url_lower = url.split("#", 1)[0].lower()
    if url_lower.startswith("http") and "macquarie.com" not in url_lower:
        return None
    path = url_lower.split("?", 1)[0]
    # A PDF, or a report detail page such as /investors/reports/full-year-
    # 2026.html, but not the listing page itself.
    if path.endswith(".pdf") or re.search(r"/investors/reports/[^/]+\.html$", path):
        return text
    return None
