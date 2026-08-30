import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, async_playwright

from ..base import Announcement, BaseScraper


class COHScraper(BaseScraper):
    """Cochlear ASX announcements scraper via IRM feed iframe source."""

    IRM_BASE = "https://coh.live.irmau.com/irm/ShowCategory.aspx"

    @property
    def ticker(self) -> str:
        return "COH"

    @property
    def source_url(self) -> str:
        return "https://www.cochlear.com/au/en/corporate/investors/asx-announcements"

    def _feed_url(self, year: int) -> str:
        return (
            f"{self.IRM_BASE}?CategoryId=8&FilterStyle=B&archive=true&year={year}"
        )

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

            now_year = datetime.now().year
            seed_page = await context.new_page()
            await seed_page.goto(
                self._feed_url(now_year),
                wait_until="networkidle",
                timeout=120000,
            )
            await seed_page.wait_for_timeout(1500)

            years = await self._extract_years(seed_page)
            await seed_page.close()

            if not years:
                years = [now_year]

            # Keep scope manageable while covering current and previous year by default.
            years = years[:2]
            print(f"[COH] Target years: {years}")

            all_rows: list[dict[str, str]] = []
            for year in years:
                feed_url = self._feed_url(year)
                page = await context.new_page()
                await page.goto(feed_url, wait_until="networkidle", timeout=120000)
                await page.wait_for_timeout(1200)

                rows = await self._extract_rows(page, feed_url)
                print(f"[COH] Year {year}: found {len(rows)} rows")
                all_rows.extend(rows)
                await page.close()

            all_rows = self._dedupe_rows(all_rows)

            for row in all_rows:
                parsed_date = self._parse_date(row["date_str"])
                if not parsed_date:
                    print(f"[COH] Could not parse date: {row['date_str']}")
                    continue

                ann = Announcement(
                    ticker=self.ticker,
                    title=row["title"],
                    date=parsed_date,
                    pdf_url=row["pdf_url"],
                    source_url=row.get("feed_url", self.source_url),
                    metadata={
                        "listing_url": self.source_url,
                        "feed_url": row.get("feed_url", self.source_url),
                        "raw_date": row["date_str"],
                        "year": row.get("year"),
                    },
                )

                try:
                    ann.local_path = await self._download_via_browser(context, ann)
                except Exception as e:
                    print(f"[COH] Failed to download '{ann.title}': {e}")

                announcements.append(ann)

            await browser.close()

        return self._dedupe_announcements(announcements)

    async def _extract_years(self, page) -> list[int]:
        year_texts = await page.evaluate(
            """() => {
                return Array.from(document.querySelectorAll('a[id*="lnkbtnYear"], a'))
                    .map(a => (a.textContent || '').trim())
                    .filter(t => /^\d{4}$/.test(t));
            }"""
        )

        years: list[int] = []
        for text in year_texts:
            try:
                year = int(text)
                if year not in years:
                    years.append(year)
            except ValueError:
                pass

        # Newest first is already how IRM renders the year links.
        return years

    async def _extract_rows(self, page, feed_url: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []

        links = await page.query_selector_all("tr a[href]")
        for link in links:
            row = await self._build_row_from_link(link, feed_url)
            if row:
                rows.append(row)

        return rows

    async def _build_row_from_link(self, link, feed_url: str) -> dict[str, str] | None:
        href = (await link.get_attribute("href")) or ""
        title_text = ((await link.inner_text()) or "").strip()
        if not href or not title_text:
            return None

        pdf_url = href if href.startswith("http") else urljoin(feed_url, href)
        if not self._looks_like_pdf_url(pdf_url):
            return None

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
            return None

        title = self._clean_title(title_text)
        if not title:
            return None

        year = None
        match = re.search(r"(\d{4})$", date_str)
        if match:
            year = match.group(1)

        return {
            "title": title,
            "date_str": date_str,
            "pdf_url": pdf_url,
            "feed_url": feed_url,
            "year": year,
        }

    def _looks_like_pdf_url(self, url: str) -> bool:
        lowered = url.lower()
        return "/irm/pdf/" in lowered and lowered.endswith(".pdf")

    def _extract_date_string(self, text: str) -> str | None:
        normalized = re.sub(r"\s+", " ", text)
        match = re.search(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}\b", normalized)
        return match.group(0) if match else None

    def _clean_title(self, title: str) -> str:
        cleaned = re.sub(r"\s+", " ", title).strip()
        cleaned = re.sub(r"\bopens? in (a )?new window\b", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" -:\t")

    def _parse_date(self, date_str: str) -> datetime | None:
        for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d %b %Y", "%d %B %Y"):
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
            headers={"Referer": announcement.source_url or self.source_url},
        )

        if not response.ok:
            raise RuntimeError(f"HTTP {response.status} for {announcement.pdf_url}")

        body = await response.body()
        dest.write_bytes(body)

        if not body.startswith(b"%PDF"):
            raise ValueError(f"Downloaded file is not a PDF: {announcement.pdf_url}")

        print(f"[COH] Saved: {dest}")
        return dest

    async def download_pdf(self, announcement: Announcement) -> Path:
        if announcement.local_path:
            return announcement.local_path

        raise NotImplementedError(
            "COH downloads are handled inside fetch_announcements via browser context"
        )

    async def scrape(self) -> list[Announcement]:
        return await self.fetch_announcements()
