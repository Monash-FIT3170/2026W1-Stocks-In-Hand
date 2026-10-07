"""Origin Energy (ORG): media releases on Origin's investor pages.

The listing is a server-rendered WordPress page that paginates with
?query-0-page=N. Each release's article page links to one or more PDFs;
when there are several, the one labelled ASX is the lodged document rather
than a supplementary report.
"""

from __future__ import annotations

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..article_listings import (
    MONTH_FIRST_DATES,
    ArticleLink,
    article_pdf_url,
    dated_links,
    resolved_announcements,
    walk_listing_pages,
)
from ..base import Announcement
from ..fetching import Page, Render

# The listing goes back about 66 pages; keep to the recent ones.
MAX_PAGES = 2
# The listing is server-rendered and never reaches network idle, so wait for
# the DOM and the release links.
LISTING = Render(wait_for="a[href*='/about/investors-media/']")
ARTICLE = Render(settle_ms=1_000)


def listing_page_url(listing_url: str, page_number: int) -> str:
    return listing_url if page_number == 1 else f"{listing_url}?query-0-page={page_number}"


class ORGAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset({"www.originenergy.com.au", "originenergy.com.au"})

    async def _list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(ignore_https_errors=True) as web:
            links = await walk_listing_pages(
                web,
                [listing_page_url(self.source_url, number) for number in range(1, MAX_PAGES + 1)],
                LISTING,
                lambda page, url: release_links(page, page_url=url, listing_url=self.source_url),
            )

            async def pdf_url_for(link: ArticleLink) -> str | None:
                article = await web.render(link.article_url, ARTICLE)
                return article_pdf_url(article, link.article_url, prefer=_asx_labelled)

            return await resolved_announcements(
                links, pdf_url_for, ticker=self.ticker, listing_url=self.source_url
            )


def release_links(listing: Page, *, page_url: str, listing_url: str) -> list[ArticleLink]:
    def title_for(url: str, text: str) -> str | None:
        url_lower = url.lower().split("#", 1)[0]
        if not text:
            return None
        if url_lower.startswith("http") and "originenergy.com.au" not in url_lower:
            return None
        if "/about/investors-media/" not in url_lower:
            return None
        # Not tag chips, pagination or the listing linking to itself.
        if "/tag/" in url_lower or "query-0-page" in url_lower:
            return None
        if url_lower.rstrip("/") == listing_url.lower().rstrip("/"):
            return None
        return text

    # The listing prints "July 31, 2026" and article pages "31 July 2026".
    return dated_links(
        listing, base_url=page_url, rules=MONTH_FIRST_DATES, title_for=title_for
    )


def _asx_labelled(url: str, text: str) -> bool:
    # The ASX-labelled attachment is the document lodged with the exchange.
    return "asx" in text.lower() or "asx" in url.lower()
