from datetime import datetime
import re

from playwright.async_api import async_playwright

from ..base import BaseScraper, Announcement

YOURIR_BASE = "https://yourir.info/resources/4d216b570d08af30/announcements"


class ANZScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "ANZ"

    @property
    def source_url(self) -> str:
        return "https://www.anz.com/shareholder/centre/investor-toolkit/asx-announcements/"

    async def fetch_announcements(self) -> list[Announcement]:
        announcements = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page()

            try:
                await page.goto(self.source_url, wait_until="networkidle")
                await page.wait_for_selector("tbody[data-yourir='items'] tr")

                rows = await page.query_selector_all("tbody[data-yourir='items'] tr")

                for row in rows:
                    date_cell = await row.query_selector("td.views-field-created")
                    title_cell = await row.query_selector(
                        "td.yourir-announcement-heading a"
                    )

                    if not date_cell or not title_cell:
                        continue

                    date_str = (await date_cell.inner_text()).strip()
                    title = await title_cell.get_attribute("title")
                    yourir_id = await row.get_attribute("data-yourir-id")
                    if not title or not yourir_id:
                        continue
                    pdf_url = self._build_pdf_url(yourir_id, title)

                    announcements.append(
                        Announcement(
                            ticker=self.ticker,
                            title=title,
                            date=datetime.strptime(date_str, "%d/%m/%Y"),
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
        filename = f"ANZ_{filename}.pdf"
        return f"{YOURIR_BASE}/{yourir_id}/{filename}"
