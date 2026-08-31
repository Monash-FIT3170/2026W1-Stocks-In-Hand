from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from ..base import BaseScraper, Announcement
from ..browser import chromium_launch_options


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
            browser = await p.chromium.launch(**chromium_launch_options())

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

                announcements.append(
                    Announcement(
                        ticker=self.ticker,
                        title=title,
                        date=parsed_date,
                        pdf_url=pdf_url,
                        source_url=self.source_url,
                        metadata={
                            "raw_href": href,
                            "raw_date": date_str,
                            "source_id": href,
                        },
                    )
                )

            await browser.close()

        return announcements
