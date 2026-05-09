import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright, BrowserContext

from ..base import BaseScraper, Announcement


class WESScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "WES"

    @property
    def source_url(self) -> str:
        return "https://www.wesfarmers.com.au/investor-centre/company-performance-news/asx-announcements"

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
            await page.wait_for_selector(
                "article.asx-announce div.asx-results li",
                timeout=15000,
            )

            rows = await page.query_selector_all(
                "article.asx-announce div.asx-results li"
            )
            print(f"[WES] Found {len(rows)} announcement rows")

            for row in rows:
                date_el = await row.query_selector("span.date-time")
                link = await row.query_selector("a[href]")

                if not date_el or not link:
                    continue

                date_str = (await date_el.inner_text()).strip()
                title = (await link.inner_text()).strip()
                href = await link.get_attribute("href")

                if not date_str or not title or not href:
                    continue

                pdf_url = href if href.startswith("http") else urljoin(self.source_url, href)

                announcements.append(
                    Announcement(
                        ticker=self.ticker,
                        title=title,
                        date=datetime.strptime(date_str, "%d.%m.%y"),
                        pdf_url=pdf_url,
                        source_url=self.source_url,
                        metadata={"raw_href": href, "raw_date": date_str},
                    )
                )

            # Single listing page load, click each link and intercept the PDF request
            for ann in announcements:
                try:
                    ann.local_path = await self._download_via_browser(context, ann)
                except Exception as e:
                    print(f"[WES] Failed to download '{ann.title}': {e}")

            await browser.close()

        return announcements

    async def _download_via_browser(
        self, context: BrowserContext, announcement: Announcement
    ) -> Path:
        date_str = announcement.date.strftime("%Y-%m-%d")
        clean_title = re.sub(r"[^\w\-_]", "_", announcement.title)
        filename = f"{date_str}_{clean_title}.pdf"
        dest = self.output_dir / filename

        response = await context.request.get(
            announcement.pdf_url,  # already has auth_token from the href
            headers={"Referer": self.source_url},
        )

        if not response.ok:
            raise Exception(f"HTTP {response.status} for {announcement.pdf_url}")

        body = await response.body()
        if body[:4] != b"%PDF":
            raise Exception(f"Response is not a PDF: {body[:50]}")

        dest.write_bytes(body)
        print(f"[WES] Saved: {dest}")
        return dest

    async def download_pdf(self, announcement: Announcement) -> Path:
        # download_pdf is called by BaseScraper.scrape() but for WES we
        # handle downloading inside fetch_announcements to reuse the browser
        # context. This method is a no-op fallback.
        if announcement.local_path:
            return announcement.local_path
        raise NotImplementedError(
            "WES downloads are handled inside fetch_announcements via browser context"
        )
    

    async def scrape(self) -> list[Announcement]:
        return await self.fetch_announcements()