"""Origin Energy (ORG): media releases on Origin's investor pages.

The listing is a server-rendered WordPress page that paginates with
?query-0-page=N. Each release's article page links to one or more PDFs;
when there are several, the one labelled ASX is the lodged document rather
than a supplementary report.
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
        announcements: list[Announcement] = []
        failures: list[SourceUnreachableError] = []
        async with self.fetcher.session(ignore_https_errors=True) as web:
            article_links: list[dict] = []
            for page_number in range(1, MAX_PAGES + 1):
                page_url = listing_page_url(self.source_url, page_number)
                try:
                    listing = await web.render(page_url, LISTING)
                except SourceUnreachableError:
                    if page_number == 1:
                        raise
                    break
                known = {item["article_url"] for item in article_links}
                new_items = [
                    item
                    for item in release_links(listing, page_url=page_url, listing_url=self.source_url)
                    if item["article_url"] not in known
                ]
                if not new_items:
                    break
                article_links.extend(new_items)

            for item in article_links:
                try:
                    article = await web.render(item["article_url"], ARTICLE)
                except SourceUnreachableError as exc:
                    LOGGER.warning("ORG release %s failed: %s", item["article_url"], exc)
                    failures.append(exc)
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
                            "listing_url": self.source_url,
                            "article_url": item["article_url"],
                            "raw_date": item["raw_date"],
                        },
                    )
                )
        if failures and not announcements:
            raise failures[0]
        return _dedupe(announcements)


def release_links(listing: Page, *, page_url: str, listing_url: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for link in parse_html(listing.html).select("a[href]"):
        href = link.get("href")
        text = link.text.strip()
        if not href:
            continue
        article_url = urljoin(page_url, href)
        if not _looks_like_release(article_url, text, listing_url):
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
    candidates: list[tuple[str, str]] = []
    for link in parse_html(article.html).select("a[href*='.pdf']"):
        href = link.get("href")
        if not href:
            continue
        full_url = urljoin(article_url, href)
        if ".pdf" in full_url.lower():
            candidates.append((full_url, link.text.strip()))
    if not candidates:
        match = re.search(r'https?://[^"\']+\.pdf(?:\?[^"\']*)?', article.html)
        if match:
            return match.group(0)
        relative = re.search(r'["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', article.html)
        if relative:
            return urljoin(article_url, relative.group(1))
        return None
    # Prefer the attachment labelled ASX: that is the document lodged with
    # the exchange, not a supplementary report.
    for full_url, text in candidates:
        if "asx" in text.lower() or "asx" in full_url.lower():
            return full_url
    return candidates[0][0]


def _looks_like_release(url: str, text: str, listing_url: str) -> bool:
    url_lower = url.lower().split("#", 1)[0]
    if not text:
        return False
    if url_lower.startswith("http") and "originenergy.com.au" not in url_lower:
        return False
    if "/about/investors-media/" not in url_lower:
        return False
    # Not tag chips, pagination or the listing linking to itself.
    if "/tag/" in url_lower or "query-0-page" in url_lower:
        return False
    return url_lower.rstrip("/") != listing_url.lower().rstrip("/")


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
        r"[A-Za-z]+\s+\d{1,2},\s*\d{4}",  # July 31, 2026 (listing page)
        r"\d{1,2}\s+[A-Za-z]+\s+\d{4}",  # 31 July 2026 (article page)
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
