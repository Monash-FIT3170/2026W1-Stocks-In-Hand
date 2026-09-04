from datetime import datetime
import re

from playwright.async_api import async_playwright

from ..base import BaseScraper, Announcement
from ..browser import chromium_launch_options

YOURIR_BASE = "https://yourir.info/resources/e381e7bfa5abbe55/announcements"


class CBAScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "CBA"

    @property
    def source_url(self) -> str:
        return "https://www.commbank.com.au/about-us/investors/asx-announcements.html"

    async def fetch_announcements(self) -> list[Announcement]:
        announcements = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(**chromium_launch_options())
            page = await browser.new_page()

            try:
                await page.goto(self.source_url, wait_until="networkidle")
                await page.wait_for_selector(
                    "div.table-body[data-yourir-items='true'] "
                    "div.table-row[data-yourir-id]",
                    timeout=15000,
                )

                rows = await page.query_selector_all(
                    "div.table-body[data-yourir-items='true'] "
                    "div.table-row[data-yourir-id]"
                )

                print(f"[CBA] Found {len(rows)} announcement rows")

                for row in rows:
                    row_text = (await row.inner_text()).strip()
                    yourir_id = await row.get_attribute("data-yourir-id")
                    if not yourir_id or not row_text:
                        continue

                    lines = [
                        line.strip()
                        for line in row_text.splitlines()
                        if line.strip()
                    ]
                    if len(lines) < 2:
                        continue

                    date_str = lines[0]
                    title = lines[1]

                    try:
                        parsed_date = datetime.strptime(date_str, "%d %b %Y")
                    except ValueError:
                        try:
                            parsed_date = datetime.strptime(date_str, "%d %B %Y")
                        except ValueError:
                            print(f"[CBA] Could not parse date: {date_str}")
                            continue

                    pdf_url = self._build_pdf_url(yourir_id, title)
                    announcements.append(
                        Announcement(
                            ticker=self.ticker,
                            title=title,
                            date=parsed_date,
                            pdf_url=pdf_url,
                            source_url=self.source_url,
                            metadata={
                                "yourir_id": yourir_id,
                                "source_id": yourir_id,
                            },
                        )
                    )
            finally:
                await browser.close()

        return announcements

    def _build_pdf_url(self, yourir_id: str, title: str) -> str:
        filename = re.sub(r"[^\w\s]", "", title)
        filename = re.sub(r"\s+", "_", filename.strip())
        filename = f"CBA_{filename}.pdf"
        return f"{YOURIR_BASE}/{yourir_id}/{filename}"
