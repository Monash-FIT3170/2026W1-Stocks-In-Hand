"""Sites that list announcements as links to article pages that link the PDF.

Macquarie, Origin, Rio Tinto and Woodside list dated links (some pages
paginate); each link opens an article page whose first PDF link is the
document, unless the link is a PDF already. Listing resolves every article
to its PDF, so Queue B carries a direct document URL.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

from .base import Announcement
from .fetching import Page, Render, SourceUnreachableError
from .html import Element, nearby_text_levels, parse_html
from .parsing import (
    DAY_MONTH_YEAR,
    DOTTED,
    ISO,
    MONTH_DAY_YEAR,
    SLASHED,
    first_date,
    parse_date,
    unique,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DateRules:
    """How one site prints dates near its links."""

    patterns: Sequence[str]
    formats: Sequence[str]

    def parse(self, value: str) -> datetime | None:
        return parse_date(value, self.formats, iso_fallback=True)

    def find(self, text: str) -> datetime | None:
        return first_date(text, self.patterns, self.formats, iso_fallback=True)


_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%d/%m/%Y",
    "%d.%m.%y",
)
# Rio Tinto and Woodside print "29 July 2026"; Macquarie and Origin may also
# print "July 31, 2026", which is tried first.
DAY_FIRST_DATES = DateRules(patterns=(DAY_MONTH_YEAR, SLASHED, DOTTED, ISO), formats=_FORMATS)
MONTH_FIRST_DATES = DateRules(
    patterns=(MONTH_DAY_YEAR, DAY_MONTH_YEAR, SLASHED, DOTTED, ISO),
    formats=_FORMATS,
)


@dataclass(frozen=True)
class ArticleLink:
    title: str
    date: datetime
    article_url: str


def link_date(link: Element, rules: DateRules) -> datetime | None:
    """The date in a link's narrowest dated container.

    A ``time[datetime]`` nearby wins. Otherwise each ancestor's text is
    searched, nearest first, stopping before a container wider than a row,
    so a neighbouring row's date is never used.
    """
    time_value, levels = nearby_text_levels(link)
    if time_value:
        parsed = rules.parse(time_value.strip()[:19].replace("T", " "))
        if parsed:
            return parsed
    for text in levels:
        if len(text) > 2000:
            break
        parsed = rules.find(text)
        if parsed:
            return parsed
    return None


def dated_links(
    page: Page,
    *,
    base_url: str,
    rules: DateRules,
    title_for: Callable[[str, str], str | None],
    selector: str = "a[href]",
) -> list[ArticleLink]:
    """Dated links on a listing page, first of each URL, in page order.

    ``title_for(url, link_text)`` returns the link's title, or None to skip
    a link that is not an announcement.
    """
    links: list[ArticleLink] = []
    for link in parse_html(page.html).select(selector):
        href = link.get("href")
        if not href:
            continue
        url = urljoin(base_url, href)
        title = title_for(url, link.text.strip())
        if title is None:
            continue
        date = link_date(link, rules)
        if date is not None:
            links.append(ArticleLink(title=title, date=date, article_url=url))
    return unique(links, key=lambda link: link.article_url)


def article_pdf_url(
    article: Page,
    article_url: str,
    *,
    prefer: Callable[[str, str], bool] | None = None,
    drop_fragment: bool = False,
) -> str | None:
    """The document an article page links to.

    The first PDF link wins, or the first ``prefer``-red one; failing any
    link, the first PDF URL anywhere in the page source.
    """

    def clean(url: str) -> str:
        return url.split("#", 1)[0] if drop_fragment else url

    candidates = []
    for link in parse_html(article.html).select("a[href*='.pdf']"):
        href = link.get("href")
        if not href:
            continue
        url = clean(urljoin(article_url, href))
        if ".pdf" in url.lower():
            candidates.append((url, link.text.strip()))
    if candidates:
        if prefer:
            for url, text in candidates:
                if prefer(url, text):
                    return url
        return candidates[0][0]
    absolute = re.search(r'https?://[^"\']+\.pdf(?:\?[^"\']*)?', article.html)
    if absolute:
        return clean(absolute.group(0))
    relative = re.search(r'["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', article.html)
    if relative:
        return clean(urljoin(article_url, relative.group(1)))
    return None


async def walk_listing_pages(
    web,
    page_urls: Sequence[str],
    render: Render,
    links_on: Callable[[Page, str], list[ArticleLink]],
) -> list[ArticleLink]:
    """Links from successive listing pages until a page adds nothing new.

    The first page must load; a later page that fails ends the walk.
    """
    links: list[ArticleLink] = []
    for number, url in enumerate(page_urls):
        try:
            page = await web.render(url, render)
        except SourceUnreachableError:
            if number == 0:
                raise
            break
        known = {link.article_url for link in links}
        new = [link for link in links_on(page, url) if link.article_url not in known]
        if not new:
            break
        links.extend(new)
    return links


async def resolved_announcements(
    links: Sequence[ArticleLink],
    pdf_url_for: Callable[[ArticleLink], Awaitable[str | None]],
    *,
    ticker: str,
    listing_url: str,
) -> list[Announcement]:
    """One announcement per link whose article names a PDF.

    An article that cannot be loaded is skipped, unless every one fails,
    which makes the source unreachable.
    """
    announcements: list[Announcement] = []
    failures: list[SourceUnreachableError] = []
    for link in links:
        try:
            pdf_url = await pdf_url_for(link)
        except SourceUnreachableError as exc:
            LOGGER.warning("%s article %s failed: %s", ticker, link.article_url, exc)
            failures.append(exc)
            continue
        if pdf_url:
            announcements.append(
                Announcement(
                    ticker=ticker,
                    title=link.title,
                    date=link.date,
                    pdf_url=pdf_url,
                    source_url=link.article_url,
                    metadata={
                        "listing_url": listing_url,
                        "article_url": link.article_url,
                        "raw_date": link.date.isoformat(),
                    },
                )
            )
    if failures and not announcements:
        raise failures[0]
    return unique(announcements, key=lambda item: item.pdf_url)
