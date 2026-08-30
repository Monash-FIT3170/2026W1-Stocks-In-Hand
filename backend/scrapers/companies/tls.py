import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, async_playwright

from ..base import Announcement, BaseScraper


class TLSScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "TLS"

    @property
    def source_url(self) -> str:
        return "https://www.telstra.com.au/aboutus/investors/announcements"

    async def fetch_announcements(self) -> list[Announcement]:
        announcements: list[Announcement] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--headless=new",
                ],
            )

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
                locale="en-AU",
                ignore_https_errors=True,
            )

            page = await context.new_page()
            await page.goto(self.source_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            rows = await self._extract_rows(page)
            print(f"[TLS] Found {len(rows)} announcement rows")

            for row in rows:
                try:
                    date = self._parse_date(row["date_str"])
                    if not date:
                        print(f"[TLS] Could not parse date: {row['date_str']}")
                        continue

                    ann = Announcement(
                        ticker=self.ticker,
                        title=row["title"],
                        date=date,
                        pdf_url=row["pdf_url"],
                        source_url=row.get("source_url", self.source_url),
                        metadata={
                            "listing_url": self.source_url,
                            "feed_url": row.get("feed_url"),
                            "raw_date": row["date_str"],
                        },
                    )

                    announcements.append(ann)
                except Exception as e:
                    print(f"[TLS] Failed to process row: {e}")

            await browser.close()

        return self._dedupe_announcements(announcements)

    async def _extract_rows(self, page) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []

        feed_frame = await self._resolve_feed_frame(page)
        if not feed_frame:
            print("[TLS] Could not locate announcements iframe")
            return rows

        links = await feed_frame.query_selector_all("a[href*='DownloadFile.axd']")
        frame_url = feed_frame.url

        for link in links:
            href = await link.get_attribute("href")
            title_text = (await link.inner_text()).strip()

            if not href:
                continue

            pdf_url = href if href.startswith("http") else urljoin(frame_url, href)
            if not self._looks_like_announcement_pdf(pdf_url, title_text):
                continue

            row_text = (
                (
                    await link.evaluate(
                        "el => (el.closest('tr, li, article, section, div') || el).innerText"
                    )
                )
                or ""
            ).strip()

            date_str = self._extract_date_string(row_text)
            if not date_str:
                continue

            title = self._clean_title(title_text, row_text, pdf_url)
            if not title:
                continue

            rows.append(
                {
                    "title": title,
                    "date_str": date_str,
                    "pdf_url": pdf_url,
                    "source_url": frame_url,
                    "feed_url": frame_url,
                }
            )

        return self._dedupe_rows(rows)

    async def _resolve_feed_frame(self, page):
        """Telstra renders ASX rows inside a Miraqle iframe."""
        for _ in range(12):
            for frame in page.frames:
                if "events.miraqle.com" in frame.url and "iFrames" in frame.url:
                    return frame
            await page.wait_for_timeout(500)
        return None

    def _looks_like_announcement_pdf(self, url: str, title: str) -> bool:
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
                "announcement",
                "asx",
                "results",
                "dividend",
                "appendix",
                "investor",
                "quarter",
                "half-year",
                "annual",
            ]
            return any(term in lowered_url or term in lowered_title for term in useful_terms)

        return False

    def _extract_date_string(self, text: str) -> str | None:
        normalized = re.sub(r"\s+", " ", text)

        patterns = [
            r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",  # 8 August 2026
            r"\b\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\b", # 8 Aug 2026
            r"\b\d{1,2}/\d{1,2}/\d{4}\b",          # 08/08/2026
            r"\b\d{4}-\d{2}-\d{2}\b",              # 2026-08-08
        ]

        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                return match.group(0)

        return None

    def _clean_title(self, title_text: str, row_text: str, pdf_url: str) -> str:
        if title_text:
            cleaned = re.sub(r"\s+", " ", title_text).strip()
            cleaned = re.sub(r"\(PDF[^\)]*\)", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\bopens? in (a )?new window\b", "", cleaned, flags=re.IGNORECASE)
            cleaned = cleaned.strip(" -:\t")
            if cleaned:
                return cleaned

        # Fallback from container text.
        cleaned = re.sub(r"\s+", " ", row_text).strip()
        cleaned = re.sub(r"\bView PDF\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\(PDF[^\)]*\)", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bopens? in (a )?new window\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b", "", cleaned)
        cleaned = cleaned.strip(" -:\t")
        if cleaned:
            return cleaned

        # Last fallback: derive a readable title from the URL filename.
        tail = pdf_url.rstrip("/").split("/")[-1]
        tail = tail.split("?")[0]
        tail = re.sub(r"\.pdf$", "", tail, flags=re.IGNORECASE)
        tail = tail.replace("-", " ").replace("_", " ")
        return re.sub(r"\s+", " ", tail).strip() or "announcement"

    def _parse_date(self, date_str: str) -> datetime | None:
        for fmt in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                pass
        return None

    def _dedupe_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        result: list[dict[str, str]] = []

        for row in rows:
            key = row["pdf_url"]
            if key in seen:
                continue
            seen.add(key)
            result.append(row)

        return result

    def _dedupe_announcements(self, announcements: list[Announcement]) -> list[Announcement]:
        seen: set[str] = set()
        result: list[Announcement] = []

        for ann in announcements:
            key = ann.pdf_url or ann.source_url or ann.title
            if key in seen:
                continue
            seen.add(key)
            result.append(ann)

        return result

    async def _download_via_browser(self, context: BrowserContext, announcement: Announcement) -> Path:
        date_str = announcement.date.strftime("%Y-%m-%d")
        clean_title = re.sub(r"[^\w-]", "_", " ".join(announcement.title.split()))
        clean_title = clean_title[:120].strip("_") or "announcement"
        filename = f"{date_str}_{clean_title}.pdf"
        dest = self.output_dir / filename

        response = await context.request.get(
            announcement.pdf_url,
            headers={"Referer": self.source_url},
        )

        if not response.ok:
            raise RuntimeError(f"HTTP {response.status} for {announcement.pdf_url}")

        body = await response.body()
        dest.write_bytes(body)

        if not body.startswith(b"%PDF"):
            raise ValueError(f"Downloaded file is not a PDF: {announcement.pdf_url}")

        print(f"[TLS] Saved: {dest}")
        return dest
