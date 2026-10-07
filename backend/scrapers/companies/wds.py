"""Woodside (WDS): the announcements list in Woodside's media centre.

The list is filled client-side and paginates with ?pageNo=N. Rows link
either straight to a PDF under /docs/default-source/ or to a detail page
that embeds one; both are handled.
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

    async def list_documents(self) -> list[Announcement]:
        announcements: list[Announcement] = []
        async with self.fetcher.session(ignore_https_errors=True) as web:
            article_links: list[dict] = []
            for page_number in range(1, MAX_PAGES + 1):
                page_url = listing_page_url(self.source_url, page_number)
                try:
                    listing = await web.render(page_url, LISTING)
                except SourceUnavailableError:
                    break
                known = {item["article_url"] for item in article_links}
                new_items = [
                    item
                    for item in announcement_links(listing, page_url=page_url, listing_url=self.source_url)
                    if item["article_url"] not in known
                ]
                if not new_items:
                    break
                article_links.extend(new_items)

            for item in article_links:
                try:
                    pdf_url = await self._pdf_url(web, item["article_url"])
                except SourceUnavailableError as exc:
                    LOGGER.warning("WDS announcement %s failed: %s", item["article_url"], exc)
                    continue
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
                            "listing_url": self.source_url,
                            "article_url": item["article_url"],
                            "raw_date": item["raw_date"],
                        },
                    )
                )
        return _dedupe(announcements)

    async def _pdf_url(self, web, article_url: str) -> str | None:
        if article_url.lower().split("?", 1)[0].endswith(".pdf"):
            return article_url
        return article_pdf_url(await web.render(article_url, ARTICLE), article_url)


def announcement_links(listing: Page, *, page_url: str, listing_url: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for link in parse_html(listing.html).select("a[href]"):
        href = link.get("href")
        text = link.text.strip()
        if not href:
            continue
        article_url = urljoin(page_url, href)
        if not _looks_like_announcement(article_url, listing_url):
            continue
        title = text or _title_from_url(article_url)
        date = _nearby_date(link)
        if date is None or article_url in seen:
            continue
        seen.add(article_url)
        items.append(
            {
                "title": title,
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


def _looks_like_announcement(url: str, listing_url: str) -> bool:
    url_lower = url.lower()
    if url_lower.startswith("http") and "woodside.com" not in url_lower:
        return False
    if url_lower.split("?", 1)[0].endswith(".pdf"):
        return True
    return (
        "/media-centre/announcements/" in url_lower
        and url_lower.rstrip("/") != listing_url.lower()
    )


def _title_from_url(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    slug = re.sub(r"\.pdf$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"^\d+[-_]", "", slug)  # strip leading "017-" style prefixes
    return slug.replace("-", " ").replace("_", " ").strip().title() or "Announcement"


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
        r"\d{1,2}\s+[A-Za-z]+\s+\d{4}",  # 16 March 2026
        r"\d{1,2}/\d{1,2}/\d{4}",  # 16/03/2026
        r"\d{1,2}\.\d{1,2}\.\d{2}\b",  # 16.03.26
        r"\d{4}-\d{2}-\d{2}",  # 2026-03-16
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
    # Tolerate full ISO-8601 timestamps such as 2026-06-25T02:00:00.000Z.
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
