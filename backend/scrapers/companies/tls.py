"""Telstra (TLS): the Miraqle feed framed on its announcements page."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from ..adapter import SeededBrowserDownload, SourceAdapter
from ..base import Announcement
from ..fetching import Page, Render
from ..html import parse_html

# Telstra renders its ASX rows inside a Miraqle iframe.
LISTING = Render(settle_ms=3_000, frame_url_contains=("events.miraqle.com", "iFrames"))


class TLSAdapter(SeededBrowserDownload, SourceAdapter):
    hosts = frozenset({"www.telstra.com.au", "telstra.com.au", "events.miraqle.com"})

    async def _list_documents(self) -> list[Announcement]:
        async with self.fetcher.session(ignore_https_errors=True) as web:
            frame = await web.render(self.source_url, LISTING)
        return parse_feed_frame(frame, ticker=self.ticker, source_url=self.source_url)


def parse_feed_frame(frame: Page, *, ticker: str, source_url: str) -> list[Announcement]:
    rows: list[dict[str, str]] = []
    for link in parse_html(frame.html).select("a[href*='DownloadFile.axd']"):
        href = link.get("href")
        if not href:
            continue
        title_text = link.text.strip()
        pdf_url = href if href.startswith("http") else urljoin(frame.url, href)
        if not _looks_like_announcement_pdf(pdf_url, title_text):
            continue
        row_text = (link.closest("tr, li, article, section, div") or link).text
        date_text = _date_text(row_text)
        if not date_text:
            continue
        title = _clean_title(title_text, row_text, pdf_url)
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
                source_url=frame.url,
                metadata={
                    "listing_url": source_url,
                    "feed_url": frame.url,
                    "raw_date": row["date_str"],
                },
            )
        )
    return announcements


def _looks_like_announcement_pdf(url: str, title: str) -> bool:
    lowered_url = url.lower()
    lowered_title = title.lower()
    if not any(host in lowered_url for host in ["telstra.com.au", "events.miraqle.com"]):
        if lowered_url.startswith("http"):
            return False
    if "downloadfile.axd" in lowered_url:
        return True
    if "telstra.com.au" not in lowered_url and lowered_url.startswith("http"):
        return False
    if ".pdf" in lowered_url:
        useful_terms = [
            "announcement", "asx", "results", "dividend", "appendix",
            "investor", "quarter", "half-year", "annual",
        ]
        return any(term in lowered_url or term in lowered_title for term in useful_terms)
    return False


def _date_text(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text)
    for pattern in (
        r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",  # 8 August 2026
        r"\b\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\b",  # 8 Aug 2026
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",  # 08/08/2026
        r"\b\d{4}-\d{2}-\d{2}\b",  # 2026-08-08
    ):
        match = re.search(pattern, normalized)
        if match:
            return match.group(0)
    return None


def _clean_title(title_text: str, row_text: str, pdf_url: str) -> str:
    if title_text:
        cleaned = re.sub(r"\s+", " ", title_text).strip()
        cleaned = re.sub(r"\(PDF[^\)]*\)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bopens? in (a )?new window\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" -:\t")
        if cleaned:
            return cleaned
    cleaned = re.sub(r"\s+", " ", row_text).strip()
    cleaned = re.sub(r"\bView PDF\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\(PDF[^\)]*\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bopens? in (a )?new window\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b", "", cleaned)
    cleaned = cleaned.strip(" -:\t")
    if cleaned:
        return cleaned
    # Last fallback: a readable title from the URL's file name.
    tail = pdf_url.rstrip("/").split("/")[-1].split("?")[0]
    tail = re.sub(r"\.pdf$", "", tail, flags=re.IGNORECASE)
    tail = tail.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", tail).strip() or "announcement"


def _parse_date(value: str) -> datetime | None:
    for fmt in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
