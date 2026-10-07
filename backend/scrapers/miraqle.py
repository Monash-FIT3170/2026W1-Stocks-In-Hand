"""Announcement tables served by Miraqle's ASX module (DownloadFile.axd links).

Coles shows the table on its own investor page and Telstra frames it from
events.miraqle.com. Each row links a document through DownloadFile.axd and
prints the date next to it.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from .base import Announcement
from .fetching import Page
from .html import parse_html
from .parsing import DAY_MONTH_YEAR, ISO, SLASHED, date_text, parse_date, unique

DATE_PATTERNS = (DAY_MONTH_YEAR, SLASHED, ISO)
DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d")


def parse_table(
    page: Page,
    *,
    ticker: str,
    listing_url: str,
    hosts: frozenset[str],
    row_selector: str,
    framed: bool = False,
) -> list[Announcement]:
    """One announcement per dated DownloadFile.axd link on the adapter's hosts.

    A framed table (``framed``) records the frame as each announcement's
    source and feed URL, so download can open it again.
    """
    base_url = page.url if framed else listing_url
    rows = []
    for link in parse_html(page.html).select("a[href*='DownloadFile.axd']"):
        href = link.get("href")
        if not href:
            continue
        pdf_url = href if href.startswith("http") else urljoin(base_url, href)
        if (urlsplit(pdf_url).hostname or "").lower() not in hosts:
            continue
        row_text = (link.closest(row_selector) or link).text
        raw_date = date_text(row_text, DATE_PATTERNS)
        if not raw_date:
            continue
        title = clean_title(link.text.strip(), row_text, pdf_url)
        if title:
            rows.append((title, raw_date, pdf_url))

    announcements = []
    for title, raw_date, pdf_url in unique(rows, key=lambda row: row[2]):
        date = parse_date(raw_date, DATE_FORMATS)
        if date is None:
            continue
        metadata = {"listing_url": listing_url}
        if framed:
            metadata["feed_url"] = page.url
        metadata["raw_date"] = raw_date
        announcements.append(
            Announcement(
                ticker=ticker,
                title=title,
                date=date,
                pdf_url=pdf_url,
                source_url=base_url,
                metadata=metadata,
            )
        )
    return announcements


def clean_title(title_text: str, row_text: str, pdf_url: str) -> str:
    """The link's own text without screen-reader labels, else the row's, else the file name."""
    for text, extra in ((title_text, False), (row_text, True)):
        cleaned = re.sub(r"\s+", " ", text).strip()
        if extra:
            cleaned = re.sub(r"\bView PDF\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\(PDF[^\)]*\)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bopens? in (a )?new window\b", "", cleaned, flags=re.IGNORECASE)
        if extra:
            cleaned = re.sub(rf"\b{DAY_MONTH_YEAR}\b", "", cleaned)
        cleaned = cleaned.strip(" -:\t")
        if cleaned:
            return cleaned
    tail = pdf_url.rstrip("/").split("/")[-1].split("?")[0]
    tail = re.sub(r"\.pdf$", "", tail, flags=re.IGNORECASE)
    tail = tail.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", tail).strip() or "announcement"
