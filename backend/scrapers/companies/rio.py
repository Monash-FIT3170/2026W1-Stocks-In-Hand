"""Rio Tinto (RIO): ASX releases through Rio's Euroland widget.

riotinto.com's exchange releases page frames three Euroland widgets (LSE,
ASX and SEC) that differ only by a v= parameter. Listing reads the ASX
widget's own URL from the page, falling back to the last known one, and
opens it as a page. Each release has a GetPressRelease page that links the
PDF on Euroland's CDN.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render, SourceUnavailableError
from ..html import Element, nearby_text_levels, parse_html

LOGGER = logging.getLogger(__name__)
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

    async def list_documents(self) -> list[Announcement]:
        announcements: list[Announcement] = []
        async with self.fetcher.session(ignore_https_errors=True) as web:
            try:
                feed_url = asx_feed_url(await web.render(self.source_url, WRAPPER), self.source_url)
            except SourceUnavailableError:
                feed_url = FALLBACK_ASX_FEED_URL
            try:
                feed = await web.render(feed_url, feed_render(self.clock().year))
            except SourceUnavailableError:
                return []
            for item in release_links(feed, feed_url=feed_url):
                try:
                    article = await web.render(item["article_url"], ARTICLE)
                except SourceUnavailableError as exc:
                    LOGGER.warning("RIO release %s failed: %s", item["article_url"], exc)
                    continue
                pdf_url = article_pdf_url(article, item["article_url"])
                if not pdf_url:
                    continue
                announcements.append(
                    Announcement(
                        ticker=self.ticker,
                        title=item["title"],
                        date=item["date"],
                        pdf_url=pdf_url,
                        source_url=item["article_url"],
                        metadata={
                            "listing_url": feed_url,
                            "article_url": item["article_url"],
                            "raw_date": item["raw_date"],
                        },
                    )
                )
        return _dedupe(announcements)


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


def release_links(feed: Page, *, feed_url: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for link in parse_html(feed.html).select(RELEASE_LINK):
        href = link.get("href")
        text = link.text.strip()
        if not href or not text:
            continue
        article_url = urljoin(feed_url, href)
        date = _nearby_date(link)
        if date is None or article_url in seen:
            continue
        seen.add(article_url)
        items.append(
            {
                "title": text,
                "date": date,
                "raw_date": date.isoformat(),
                "article_url": article_url,
            }
        )
    return items


def article_pdf_url(article: Page, article_url: str) -> str | None:
    for link in parse_html(article.html).select("a[href*='.pdf']"):
        href = link.get("href")
        if not href:
            continue
        full_url = urljoin(article_url, href)
        if ".pdf" in full_url.lower():
            return full_url
    match = re.search(r'https?://[^"\']+\.pdf(?:\?[^"\']*)?', article.html)
    if match:
        return match.group(0)
    relative = re.search(r'["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', article.html)
    if relative:
        return urljoin(article_url, relative.group(1))
    return None


def _dedupe(announcements: list[Announcement]) -> list[Announcement]:
    seen: set[str] = set()
    result = []
    for announcement in announcements:
        key = announcement.pdf_url or announcement.source_url or announcement.title
        if key not in seen:
            seen.add(key)
            result.append(announcement)
    return result


def _nearby_date(link: Element) -> datetime | None:
    time_value, levels = nearby_text_levels(link)
    if time_value:
        parsed = _parse_date(time_value.strip()[:19].replace("T", " "))
        if parsed:
            return parsed
    for text in levels:
        if len(text) > 2000:
            break
        parsed = _first_date_in_text(text)
        if parsed:
            return parsed
    return None


def _first_date_in_text(text: str) -> datetime | None:
    for pattern in (
        r"\d{1,2}\s+[A-Za-z]+\s+\d{4}",  # 29 July 2026
        r"\d{1,2}/\d{1,2}/\d{4}",  # 29/07/2026
        r"\d{1,2}\.\d{1,2}\.\d{2}\b",  # 29.07.26
        r"\d{4}-\d{2}-\d{2}",  # 2026-07-29
    ):
        match = re.search(pattern, text)
        if match:
            parsed = _parse_date(match.group(0))
            if parsed:
                return parsed
    return None


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d %B %Y",
        "%d %b %Y",
        "%d/%m/%Y",
        "%d.%m.%y",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
