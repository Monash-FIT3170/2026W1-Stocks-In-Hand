"""Rio Tinto (RIO): ASX releases through Rio's Euroland widget.

riotinto.com's exchange releases page frames three Euroland widgets (LSE,
ASX and SEC) that differ only by a v= parameter. Listing reads the ASX
widget's own URL from the page, falling back to the last known one, and
opens it as a page. Each release has a GetPressRelease page that links the
PDF on Euroland's CDN.
"""

from __future__ import annotations

from urllib.parse import urljoin

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..article_listings import (
    DAY_FIRST_DATES,
    ArticleLink,
    article_pdf_url,
    dated_links,
    resolved_announcements,
)
from ..base import Announcement
from ..fetching import Page, Render, SourceUnreachableError
from ..html import parse_html

# The ASX tab's widget, used when the wrapper page cannot be read (for
# example after Rio rotates the v= revision).
FALLBACK_ASX_FEED_URL = (
    "https://tools.eurolandir.com/tools/pressreleases/"
    "?companycode=uk-rio&v=asx2023&lang=en-GB"
)
WRAPPER = Render(settle_ms=1_500)
ARTICLE = Render(settle_ms=1_000)
RELEASE_LINK = "a[href*='GetPressRelease']"


def feed_render(year: int) -> Render:
    # The widget fills its table client-side; when nothing shows, click the
    # current year (or "All") the way a visitor would.
    return Render(
        wait_until="networkidle",
        wait_for=RELEASE_LINK,
        wait_for_timeout_ms=8_000,
        click_if_missing=(f"a:text-is('{year}')", "a[href*='loadAllPeriods']"),
    )


class RIOAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset(
        {
            "www.riotinto.com",
            "riotinto.com",
            "ne-cdn.eurolandir.com",
            "tools.eurolandir.com",
        }
    )

    async def _list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(ignore_https_errors=True) as web:
            try:
                wrapper = await web.render(self.source_url, WRAPPER)
                feed_url = asx_feed_url(wrapper, self.source_url)
            except SourceUnreachableError:
                feed_url = FALLBACK_ASX_FEED_URL
            feed = await web.render(feed_url, feed_render(self.clock().year))

            async def pdf_url_for(link: ArticleLink) -> str | None:
                article = await web.render(link.article_url, ARTICLE)
                return article_pdf_url(article, link.article_url)

            return await resolved_announcements(
                release_links(feed, feed_url=feed_url),
                pdf_url_for,
                ticker=self.ticker,
                listing_url=feed_url,
            )


def asx_feed_url(wrapper: Page, wrapper_url: str) -> str:
    """The ASX widget's URL, from the wrapper's frames or else its links."""
    document = parse_html(wrapper.html)
    for frame in document.select("iframe[src*='eurolandir.com']"):
        url = urljoin(wrapper_url, frame.get("src") or "")
        if "v=asx" in url.lower():
            return url
    for link in document.select("a[href*='eurolandir.com']"):
        href = link.get("href") or ""
        if "v=asx" in href.lower():
            return urljoin(wrapper_url, href)
    return FALLBACK_ASX_FEED_URL


def release_links(feed: Page, *, feed_url: str) -> list[ArticleLink]:
    return dated_links(
        feed,
        base_url=feed_url,
        rules=DAY_FIRST_DATES,
        title_for=lambda _url, text: text or None,
        selector=RELEASE_LINK,
    )
