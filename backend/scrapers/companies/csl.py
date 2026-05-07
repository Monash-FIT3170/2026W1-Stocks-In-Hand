import re
import httpx
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright

from ..base import BaseScraper, Announcement


class CSLScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "CSL"

    @property
    def source_url(self) -> str:
        return "https://investors.csl.com/investors/asx-announcements"

    async def fetch_announcements(self) -> list[Announcement]:
        announcements = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page()

            await page.goto(self.source_url, wait_until="networkidle")
            await page.wait_for_selector("div.list-item")

            items = await page.query_selector_all("div.list-item")

            for item in items:
                date_el = await item.query_selector("div.list-date")
                link_el = await item.query_selector("a.asx-document")

                if not date_el or not link_el:
                    continue

                date_str = (await date_el.inner_text()).strip()
                title = (await link_el.inner_text()).strip()
                pdf_url = await link_el.get_attribute("href")

                if not pdf_url or not pdf_url.endswith(".pdf"):
                    # Strip query params and re-check
                    pdf_url = pdf_url.split("?")[0] if pdf_url else None

                if not pdf_url:
                    print(f"[CSL] Skipping '{title}' — no PDF URL found")
                    continue

                try:
                    date = datetime.strptime(date_str, "%d-%b-%Y")
                except ValueError:
                    try:
                        date = datetime.strptime(date_str, "%d-%B-%Y")
                    except ValueError:
                        print(f"[CSL] Could not parse date '{date_str}' for '{title}'")
                        continue

                announcements.append(Announcement(
                    ticker=self.ticker,
                    title=title,
                    date=date,
                    pdf_url=pdf_url,
                    source_url=self.source_url,
                ))

            await browser.close()

        return announcements

    async def download_pdf(self, announcement: Announcement) -> Path:
        date_str = announcement.date.strftime("%Y-%m-%d")
        clean_title = re.sub(r"[^\w\-_]", "_", announcement.title)
        filename = f"{date_str}_{clean_title}.pdf"
        dest = self.output_dir / filename

        headers = {
            "Referer": self.source_url,
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            response = await client.get(announcement.pdf_url, headers=headers)
            response.raise_for_status()
            dest.write_bytes(response.content)

        print(f"[CSL] Saved: {dest}")
        return dest