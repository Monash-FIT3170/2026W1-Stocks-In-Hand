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

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render, SourceUnreachableError
from ..html import Element, nearby_text_levels, parse_html

LOGGER = logging.getLogger(__name__)
LISTING = Render(
    wait_until="networkidle",
    wait_for="a[href*='/investors/reports/'], a[href*='.pdf']",
    settle_ms=1_000,
)
ARTICLE = Render(settle_ms=1_000)


class MQGAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset({"www.macquarie.com", "macquarie.com"})

    async def _list_documents(self) -> list[Announcement]:
        announcements: list[Announcement] = []
        failures: list[SourceUnreachableError] = []
        async with self.fetcher.session(ignore_https_errors=True) as web:
            listing = await web.render(self.source_url, LISTING)
            for item in report_links(listing, listing_url=self.source_url):
                try:
                    pdf_url = await self._pdf_url(web, item["article_url"])
                except SourceUnreachableError as exc:
                    LOGGER.warning("MQG report %s failed: %s", item["article_url"], exc)
                    failures.append(exc)
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
        if failures and not announcements:
            raise failures[0]
        return _dedupe(announcements)

    async def _pdf_url(self, web, article_url: str) -> str | None:
        without_fragment = article_url.split("#", 1)[0]
        if without_fragment.lower().split("?", 1)[0].endswith(".pdf"):
            return without_fragment
        return article_pdf_url(await web.render(article_url, ARTICLE), article_url)


def report_links(listing: Page, *, listing_url: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for link in parse_html(listing.html).select("a[href]"):
        href = link.get("href")
        text = link.text.strip()
        if not href:
            continue
        article_url = urljoin(listing_url, href)
        if not _looks_like_report_link(article_url, text):
            continue
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
        full_url = urljoin(article_url, href).split("#", 1)[0]
        if ".pdf" in full_url.lower():
            return full_url
    match = re.search(r'https?://[^"\']+\.pdf(?:\?[^"\']*)?', article.html)
    if match:
        return match.group(0).split("#", 1)[0]
    relative = re.search(r'["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', article.html)
    if relative:
        return urljoin(article_url, relative.group(1)).split("#", 1)[0]
    return None


def _looks_like_report_link(url: str, text: str) -> bool:
    if not text:
        return False
    url_lower = url.split("#", 1)[0].lower()
    if url_lower.startswith("http") and "macquarie.com" not in url_lower:
        return False
    path = url_lower.split("?", 1)[0]
    if path.endswith(".pdf"):
        return True
    # A report detail page such as /investors/reports/full-year-2026.html,
    # but not the listing page itself.
    return bool(re.search(r"/investors/reports/[^/]+\.html$", path))


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
        r"[A-Za-z]+\s+\d{1,2},\s*\d{4}",  # July 31, 2026
        r"\d{1,2}\s+[A-Za-z]+\s+\d{4}",  # 31 July 2026
        r"\d{1,2}/\d{1,2}/\d{4}",  # 31/07/2026
        r"\d{1,2}\.\d{1,2}\.\d{2}\b",  # 31.07.26
        r"\d{4}-\d{2}-\d{2}",  # 2026-07-31
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
        "%B %d, %Y",
        "%b %d, %Y",
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
