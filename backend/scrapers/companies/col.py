import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, async_playwright

from ..base import Announcement, BaseScraper
from ..browser import chromium_launch_options


class COLScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "COL"

    @property
    def source_url(self) -> str:
        return "https://www.colesgroup.com.au/investors/?page=asx-announcements"

    async def fetch_announcements(self) -> list[Announcement]:
        announcements: list[Announcement] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(**chromium_launch_options())

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
            await page.wait_for_timeout(2500)

            rows = await self._extract_rows(page)
            print(f"[COL] Found {len(rows)} announcement rows")

            for row in rows:
                try:
                    date = self._parse_date(row["date_str"])
                    if not date:
                        print(f"[COL] Could not parse date: {row['date_str']}")
                        continue

                    pdf_url = row["pdf_url"]
                    title = row["title"]

                    ann = Announcement(
                        ticker=self.ticker,
                        title=title,
                        date=date,
                        pdf_url=pdf_url,
                        source_url=self.source_url,
                        metadata={
                            "listing_url": self.source_url,
                            "raw_date": row["date_str"],
                        },
                    )

                    announcements.append(ann)
                except Exception as e:
                    print(f"[COL] Failed to process row: {e}")

            await browser.close()

        return self._dedupe_announcements(announcements)

    async def _extract_rows(self, page) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []

        # Coles consistently uses DownloadFile.axd links for ASX PDFs.
        links = await page.query_selector_all("a[href*='DownloadFile.axd']")

        for link in links:
            href = await link.get_attribute("href")
            title_text = (await link.inner_text()).strip()
            row_text = ((await link.evaluate("el => (el.closest('tr, li, div, section') || el).innerText")) or "").strip()

            if not href:
                continue

            pdf_url = href if href.startswith("http") else urljoin(self.source_url, href)
            if not self._looks_like_pdf_url(pdf_url):
                continue

            date_str = self._extract_date_string(row_text)
            if not date_str:
                continue

            title = self._clean_title(title_text, row_text)
            if not title:
                continue

            rows.append(
                {
                    "title": title,
                    "date_str": date_str,
                    "pdf_url": pdf_url,
                }
            )

        return self._dedupe_rows(rows)

    def _looks_like_pdf_url(self, url: str) -> bool:
        lowered = url.lower()
        return "downloadfile.axd" in lowered or lowered.endswith(".pdf")

    def _clean_title(self, title_text: str, row_text: str) -> str:
        if title_text:
            cleaned_title = re.sub(r"\s+", " ", title_text).strip()
            cleaned_title = re.sub(
                r"\bOpens in a new Window\b",
                "",
                cleaned_title,
                flags=re.IGNORECASE,
            )
            return cleaned_title.strip(" -:\t")

        # Fallback when anchor text is empty but row text includes the title.
        cleaned = re.sub(r"\s+", " ", row_text).strip()
        cleaned = re.sub(r"\bView PDF\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bOpens in a new Window\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b", "", cleaned)
        return cleaned.strip(" -:\t")

    def _extract_date_string(self, text: str) -> str | None:
        normalized = re.sub(r"\s+", " ", text)

        patterns = [
            r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",  # 20 July 2026
            r"\b\d{1,2}/\d{1,2}/\d{4}\b",         # 20/07/2026
            r"\b\d{4}-\d{2}-\d{2}\b",             # 2026-07-20
        ]

        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                return match.group(0)
        return None

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

        # Basic safeguard to catch HTML error pages saved as .pdf.
        if not body.startswith(b"%PDF"):
            raise ValueError(f"Downloaded file is not a PDF: {announcement.pdf_url}")

        print(f"[COL] Saved: {dest}")
        return dest
