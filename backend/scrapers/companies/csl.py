from datetime import datetime
from urllib.parse import urljoin, urlsplit

from playwright.async_api import async_playwright

from ..base import BaseScraper, Announcement
from ..browser import chromium_launch_options


class CSLScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "CSL"

    @property
    def source_url(self) -> str:
        return "https://investors.csl.com/investors/asx-announcements"

    async def fetch_announcements(self) -> list[Announcement]:
        """Discover CSL documents without downloading or writing any files."""
        announcements: list[Announcement] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(**chromium_launch_options())
            page = await browser.new_page()

            try:
                await page.goto(
                    self.source_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                await page.wait_for_selector("div.list-item", timeout=30_000)

                items = await page.query_selector_all("div.list-item")

                for item in items:
                    date_el = await item.query_selector("div.list-date")
                    link_el = await item.query_selector("a.asx-document")

                    if not date_el or not link_el:
                        continue

                    date_str = (await date_el.inner_text()).strip()
                    title = (await link_el.inner_text()).strip()
                    href = await link_el.get_attribute("href")
                    if not title or not href:
                        continue

                    try:
                        date = datetime.strptime(date_str, "%d-%b-%Y")
                    except ValueError:
                        try:
                            date = datetime.strptime(date_str, "%d-%B-%Y")
                        except ValueError:
                            continue

                    document_url = urljoin(self.source_url, href)
                    if urlsplit(document_url).scheme not in {"http", "https"}:
                        continue

                    announcements.append(
                        Announcement(
                            ticker=self.ticker,
                            title=title,
                            date=date,
                            pdf_url=document_url,
                            source_url=self.source_url,
                        )
                    )
            finally:
                await browser.close()

        return announcements
