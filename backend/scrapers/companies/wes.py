import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page

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
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--headless=new",
                ],
            )

            context = await browser.new_context(
                accept_downloads=True,
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

            await page.goto(
                self.source_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

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

                try:
                    parsed_date = datetime.strptime(date_str, "%d.%m.%y")
                except ValueError:
                    print(f"[WES] Could not parse date: {date_str}")
                    continue

                pdf_url = href if href.startswith("http") else urljoin(self.source_url, href)

                ann = Announcement(
                    ticker=self.ticker,
                    title=title,
                    date=parsed_date,
                    pdf_url=pdf_url,
                    source_url=self.source_url,
                    metadata={"raw_href": href, "raw_date": date_str},
                )

                try:
                    ann.local_path = await self._download_by_click(page, link, ann)
                except Exception as e:
                    print(f"[WES] Failed to download '{ann.title}': {e}")

                announcements.append(ann)

            await browser.close()

        return announcements

    async def _download_by_click(
        self,
        page: Page,
        link,
        announcement: Announcement,
    ) -> Path:
        date_str = announcement.date.strftime("%Y-%m-%d")
        clean_title = re.sub(r"[^\w\-_]", "_", announcement.title)
        filename = f"{date_str}_{clean_title}.pdf"
        dest = self.output_dir / filename

        print(f"[WES] Clicking document link: {announcement.title}")

        async with page.expect_download(timeout=120000) as download_info:
            await link.click(modifiers=["Alt"])

        download = await download_info.value
        await download.save_as(dest)

        if not dest.exists() or dest.stat().st_size == 0:
            raise Exception("Downloaded file is empty")

        print(f"[WES] Saved: {dest}")
        return dest

    async def download_pdf(self, announcement: Announcement) -> Path:
        if announcement.local_path:
            return announcement.local_path

        raise NotImplementedError(
            "WES downloads are handled inside fetch_announcements via browser click"
        )

    async def scrape(self) -> list[Announcement]:
        return await self.fetch_announcements()