"""Cochlear (COH): the IRM announcement feed behind its ASX page.

Cochlear's page embeds an IRM feed (coh.live.irmau.com) with one page per
year. Listing reads the current year's page for the year links, then the
two newest years.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render
from ..html import Element, parse_html
from ..parsing import date_text, parse_date, unique

IRM_BASE = "https://coh.live.irmau.com/irm/ShowCategory.aspx"
YEAR_PAGE = Render(wait_until="networkidle", timeout_ms=120_000, settle_ms=1_500)


def feed_url(year: int) -> str:
    return f"{IRM_BASE}?CategoryId=8&FilterStyle=B&archive=true&year={year}"


class COHAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset({"www.cochlear.com", "cochlear.com", "coh.live.irmau.com"})

    async def _list_documents(self) -> list[Announcement]:
        current_year = self.clock().year
        async with self.fetcher.session(ignore_https_errors=True) as web:
            seed = await web.render(feed_url(current_year), YEAR_PAGE)
            # Keep scope manageable: the current and previous year by default.
            years = (feed_years(seed) or [current_year])[:2]
            pages = [
                seed if year == current_year else await web.render(feed_url(year), YEAR_PAGE)
                for year in years
            ]
        return parse_year_pages(
            [(feed_url(year), page) for year, page in zip(years, pages)],
            ticker=self.ticker,
            source_url=self.source_url,
        )


def feed_years(page: Page) -> list[int]:
    """The year links on a feed page, newest first as IRM renders them."""
    years: list[int] = []
    for link in parse_html(page.html).select("a"):
        text = link.text.strip()
        if re.fullmatch(r"\d{4}", text) and int(text) not in years:
            years.append(int(text))
    return years


def parse_year_pages(
    pages: list[tuple[str, Page]],
    *,
    ticker: str,
    source_url: str,
) -> list[Announcement]:
    rows: list[dict[str, str | None]] = []
    for url, page in pages:
        for link in parse_html(page.html).select("tr a[href]"):
            row = _row(link, url)
            if row:
                rows.append(row)

    announcements: list[Announcement] = []
    for row in unique(rows, key=lambda row: row["pdf_url"]):
        date = parse_date(row["date_str"], ("%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y"))
        if date is None:
            continue
        announcements.append(
            Announcement(
                ticker=ticker,
                title=row["title"],
                date=date,
                pdf_url=row["pdf_url"],
                source_url=row["feed_url"],
                metadata={
                    "listing_url": source_url,
                    "feed_url": row["feed_url"],
                    "raw_date": row["date_str"],
                    "year": row["year"],
                },
            )
        )
    return announcements


def _row(link: Element, feed: str) -> dict[str, str | None] | None:
    href = link.get("href") or ""
    title_text = link.text.strip()
    if not href or not title_text:
        return None
    pdf_url = href if href.startswith("http") else urljoin(feed, href)
    lowered = pdf_url.lower()
    if "/irm/pdf/" not in lowered or not lowered.endswith(".pdf"):
        return None
    row_text = (link.closest("tr, li, article, section, div") or link).text
    raw_date = date_text(row_text, (r"\d{1,2}-[A-Za-z]{3}-\d{4}",))
    if not raw_date:
        return None
    title = re.sub(r"\s+", " ", title_text).strip()
    title = re.sub(r"\bopens? in (a )?new window\b", "", title, flags=re.IGNORECASE)
    title = title.strip(" -:\t")
    if not title:
        return None
    year = re.search(r"(\d{4})$", raw_date)
    return {
        "title": title,
        "date_str": raw_date,
        "pdf_url": pdf_url,
        "feed_url": feed,
        "year": year.group(1) if year else None,
    }

