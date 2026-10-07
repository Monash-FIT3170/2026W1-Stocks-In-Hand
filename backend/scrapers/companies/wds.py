"""Woodside (WDS): the announcements list in Woodside's media centre.

The list is filled client-side and paginates with ?pageNo=N. Rows link
either straight to a PDF under /docs/default-source/ or to a detail page
that embeds one; both are handled.
"""

from __future__ import annotations

import re

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..article_listings import (
    DAY_FIRST_DATES,
    ArticleLink,
    article_pdf_url,
    dated_links,
    resolved_announcements,
    walk_listing_pages,
)
from ..base import Announcement
from ..fetching import Page, Render

# Pages of the list to walk; raise for a deeper backfill.
MAX_PAGES = 2
LISTING = Render(
    wait_until="networkidle",
    wait_for="a[href*='.pdf'], a[href*='/media-centre/announcements/']",
    settle_ms=1_500,
)
ARTICLE = Render(settle_ms=1_500)


def listing_page_url(listing_url: str, page_number: int) -> str:
    return listing_url if page_number == 1 else f"{listing_url}?pageNo={page_number}"


class WDSAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset({"www.woodside.com", "woodside.com"})

    async def _list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(ignore_https_errors=True) as web:
            links = await walk_listing_pages(
                web,
                [listing_page_url(self.source_url, number) for number in range(1, MAX_PAGES + 1)],
                LISTING,
                lambda page, url: announcement_links(
                    page, page_url=url, listing_url=self.source_url
                ),
            )

            async def pdf_url_for(link: ArticleLink) -> str | None:
                if link.article_url.lower().split("?", 1)[0].endswith(".pdf"):
                    return link.article_url
                article = await web.render(link.article_url, ARTICLE)
                return article_pdf_url(article, link.article_url)

            return await resolved_announcements(
                links, pdf_url_for, ticker=self.ticker, listing_url=self.source_url
            )


def announcement_links(listing: Page, *, page_url: str, listing_url: str) -> list[ArticleLink]:
    def title_for(url: str, text: str) -> str | None:
        url_lower = url.lower()
        if url_lower.startswith("http") and "woodside.com" not in url_lower:
            return None
        is_pdf = url_lower.split("?", 1)[0].endswith(".pdf")
        is_article = (
            "/media-centre/announcements/" in url_lower
            and url_lower.rstrip("/") != listing_url.lower()
        )
        if not (is_pdf or is_article):
            return None
        return text or _title_from_url(url)

    return dated_links(
        listing, base_url=page_url, rules=DAY_FIRST_DATES, title_for=title_for
    )


def _title_from_url(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    slug = re.sub(r"\.pdf$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"^\d+[-_]", "", slug)  # strip leading "017-" style prefixes
    return slug.replace("-", " ").replace("_", " ").strip().title() or "Announcement"
