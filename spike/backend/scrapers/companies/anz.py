import re
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright, Page, BrowserContext

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
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto(self.source_url, wait_until="networkidle")
            await page.wait_for_selector("tbody[data-yourir='items'] tr")

            rows = await page.query_selector_all("tbody[data-yourir='items'] tr")

            for row in rows:
                date_cell = await row.query_selector("td.views-field-created")
                title_cell = await row.query_selector("td.yourir-announcement-heading a")

                if not date_cell or not title_cell:
                    continue

                date_str = (await date_cell.inner_text()).strip()
                title = await title_cell.get_attribute("title")
                yourir_id = await row.get_attribute("data-yourir-id")
                pdf_url = self._build_pdf_url(yourir_id, title)

                announcements.append(Announcement(
                    ticker=self.ticker,
                    title=title,
                    date=datetime.strptime(date_str, "%d/%m/%Y"),
                    pdf_url=pdf_url,
                    source_url=self.source_url,
                    metadata={"yourir_id": yourir_id},
                ))

            # Download all PDFs within the same browser context so
            # the referer and cookies from the ANZ page are preserved
            for ann in announcements:
                try:
                    ann.local_path = await self._download_via_browser(context, ann)
                except Exception as e:
                    print(f"[ANZ] Failed to download '{ann.title}': {e}")

            await browser.close()

        return announcements

    def _build_pdf_url(self, yourir_id: str, title: str) -> str:
        filename = re.sub(r"[^\w\s]", "", title)
        filename = re.sub(r"\s+", "_", filename.strip())
        filename = f"ANZ_{filename}.pdf"
        return f"{YOURIR_BASE}/{yourir_id}/{filename}"

    async def _download_via_browser(
        self, context: BrowserContext, announcement: Announcement
    ) -> Path:
        """
        Use Playwright's API request context to download the PDF.
        This inherits cookies and headers from the browser session,
        bypassing the 403 that direct httpx requests receive.
        """
        filename = re.sub(r"[^\w\-_]", "_", announcement.title) + ".pdf"
        dest = self.output_dir / filename

        # Use the browser's request context — same session, correct referer
        response = await context.request.get(
            announcement.pdf_url,
            headers={"Referer": self.source_url},
        )

        if response.status == 404:
            # Filename didn't match — try the raw yourir_id based name
            yourir_id = announcement.metadata["yourir_id"]
            fallback = f"{YOURIR_BASE}/{yourir_id}/announcement.pdf"
            print(f"[ANZ] 404 for '{announcement.title}' — trying fallback URL")
            response = await context.request.get(
                fallback,
                headers={"Referer": self.source_url},
            )

        if not response.ok:
            raise Exception(f"HTTP {response.status} for {announcement.pdf_url}")

        dest.write_bytes(await response.body())
        print(f"[ANZ] Saved: {dest}")
        return dest

    async def download_pdf(self, announcement: Announcement) -> Path:
        # download_pdf is called by BaseScraper.scrape() but for ANZ we
        # handle downloading inside fetch_announcements to reuse the browser
        # context. This method is a no-op fallback.
        if announcement.local_path:
            return announcement.local_path
        raise NotImplementedError(
            "ANZ downloads are handled inside fetch_announcements via browser context"
        )

    async def scrape(self) -> list[Announcement]:
        # Override scrape() to skip the base class fetch→download loop
        # since ANZScraper handles both in a single browser session
        return await self.fetch_announcements()