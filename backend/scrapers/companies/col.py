"""Coles (COL): the ASX announcements on Coles Group's investor page."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render
from ..html import parse_html

LISTING = Render(settle_ms=2_500)


class COLAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset({"www.colesgroup.com.au", "colesgroup.com.au"})

    async def _list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(ignore_https_errors=True) as web:
            page = await web.render(self.source_url, LISTING)
        return parse_listing(page, ticker=self.ticker, source_url=self.source_url)


def parse_listing(page: Page, *, ticker: str, source_url: str) -> list[Announcement]:
    rows: list[dict[str, str]] = []
    # Coles consistently uses DownloadFile.axd links for ASX PDFs.
    for link in parse_html(page.html).select("a[href*='DownloadFile.axd']"):
        href = link.get("href")
        if not href:
            continue
        pdf_url = href if href.startswith("http") else urljoin(source_url, href)
        if not _looks_like_pdf_url(pdf_url):
            continue
        row_text = (link.closest("tr, li, div, section") or link).text
        date_text = _date_text(row_text)
        if not date_text:
            continue
        title = _clean_title(link.text.strip(), row_text)
        if not title:
            continue
        rows.append({"title": title, "date_str": date_text, "pdf_url": pdf_url})

    announcements: list[Announcement] = []
    seen: set[str] = set()
    for row in rows:
        if row["pdf_url"] in seen:
            continue
        seen.add(row["pdf_url"])
        date = _parse_date(row["date_str"])
        if date is None:
            continue
        announcements.append(
            Announcement(
                ticker=ticker,
                title=row["title"],
                date=date,
                pdf_url=row["pdf_url"],
                source_url=source_url,
                metadata={"listing_url": source_url, "raw_date": row["date_str"]},
            )
        )
    return announcements


def _looks_like_pdf_url(url: str) -> bool:
    lowered = url.lower()
    return "downloadfile.axd" in lowered or lowered.endswith(".pdf")


def _clean_title(title_text: str, row_text: str) -> str:
    if title_text:
        cleaned = re.sub(r"\s+", " ", title_text).strip()
        cleaned = re.sub(r"\bOpens in a new Window\b", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" -:\t")
    # Fallback when the anchor text is empty but the row text has the title.
    cleaned = re.sub(r"\s+", " ", row_text).strip()
    cleaned = re.sub(r"\bView PDF\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bOpens in a new Window\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b", "", cleaned)
    return cleaned.strip(" -:\t")


def _date_text(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text)
    for pattern in (
        r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",  # 20 July 2026
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",  # 20/07/2026
        r"\b\d{4}-\d{2}-\d{2}\b",  # 2026-07-20
    ):
        match = re.search(pattern, normalized)
        if match:
            return match.group(0)
    return None


def _parse_date(value: str) -> datetime | None:
    for fmt in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
