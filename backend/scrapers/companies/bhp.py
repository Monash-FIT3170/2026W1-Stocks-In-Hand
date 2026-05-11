import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from typing import Any

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from ..base import BaseScraper, Announcement


class BHPScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "BHP"

    @property
    def source_url(self) -> str:
        return "https://www.bhp.com/investor-hub/market-announcements"

    async def fetch_announcements(self) -> list[Announcement]:
        announcements: list[Announcement] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
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

            await page.wait_for_timeout(3000)

            article_links = await self._extract_article_links(page)

            print(f"[BHP] Found {len(article_links)} article links")

            for item in article_links:
                try:
                    pdf_url = await self._extract_pdf_from_article(
                        context,
                        item["article_url"],
                    )

                    if not pdf_url:
                        print(f"[BHP] No PDF found for: {item['title']}")
                        continue

                    announcements.append(
                        Announcement(
                            ticker=self.ticker,
                            title=item["title"],
                            date=item["date"],
                            pdf_url=pdf_url,
                            source_url=item["article_url"],
                            metadata={
                                "listing_url": self.source_url,
                                "article_url": item["article_url"],
                            },
                        )
                    )

                except Exception as e:
                    print(f"[BHP] Failed to process article {item['article_url']}: {e}")

            announcements = self._dedupe_announcements(announcements)

            for ann in announcements:
                try:
                    ann.local_path = await self._download_via_browser(context, ann)
                except Exception as e:
                    print(f"[BHP] Failed to download '{ann.title}': {e}")

            await browser.close()

        return announcements
    
    async def _extract_article_links(self, page) -> list[dict]:
        items = []

        # Start broad, then replace with the exact BHP card selector once known.
        links = await page.query_selector_all("a[href]")

        for link in links:
            href = await link.get_attribute("href")
            text = (await link.inner_text()).strip()

            if not href or not text:
                continue

            full_url = urljoin(self.source_url, href)

            if not self._looks_like_bhp_article(full_url, text):
                continue

            nearby_text = await self._get_nearby_text(link)
            date = self._extract_date(nearby_text)

            if not date:
                print(f"[BHP] Skipping article because no date found: {text}")
                continue

            items.append(
                {
                    "title": text,
                    "date": date,
                    "article_url": full_url,
                }
            )

        return self._dedupe_article_links(items)

    def _looks_like_bhp_article(self, url: str, text: str) -> bool:
        url_lower = url.lower()
        text_lower = text.lower()

        if "bhp.com" not in url_lower and url_lower.startswith("http"):
            return False

        useful_terms = [
            "market-announcements",
            "investor",
            "asx",
            "announcement",
            "results",
            "dividend",
            "operational review",
            "annual report",
            "quarterly",
        ]

        return any(term in url_lower or term in text_lower for term in useful_terms)
    
    async def _extract_pdf_from_article(
        self,
        context: Any,
        article_url: str,
    ) -> str | None:
        page = await context.new_page()

        try:
            await page.goto(
                article_url,
                wait_until="networkidle",
            )

            await page.wait_for_timeout(1500)

            # Most likely case: the article contains a normal PDF link.
            pdf_links = await page.query_selector_all("a[href*='.pdf']")

            for link in pdf_links:
                href = await link.get_attribute("href")

                if not href:
                    continue

                full_url = urljoin(article_url, href)

                if self._looks_like_pdf(full_url):
                    return full_url

            # Fallback: sometimes the PDF URL may be in the page HTML but not a visible link.
            html = await page.content()
            match = re.search(r'https?://[^"\']+\.pdf', html)

            if match:
                return match.group(0)

            relative_match = re.search(r'["\']([^"\']+\.pdf)["\']', html)

            if relative_match:
                return urljoin(article_url, relative_match.group(1))

            return None

        finally:
            await page.close()

    def _looks_like_pdf(self, url: str) -> bool:
        return ".pdf" in url.lower()
    
    
    async def _extract_nearby_date(self, link) -> datetime | None:

        container = await link.evaluate_handle(
            """
            el => el.closest('article, li, .card, .search-result, .result, div')
            """
        )

        try:
            text = await container.evaluate("el => el.innerText")
        except Exception:
            return None
        
        date_patterns = [
            r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",   # 7 May 2026
            r"\b\d{1,2}/\d{1,2}/\d{4}\b",         # 07/05/2026
            r"\b\d{4}-\d{2}-\d{2}\b",             # 2026-05-07
        ]

        for pattern in date_patterns:
            match = re.search(pattern, text)
            if not match:
                continue

            date_str = match.group(0)

            for fmt in ["%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    pass

        return None
    
    async def _download_via_browser(self, context, announcement: Announcement) -> Path:
        date_str = announcement.date.strftime("%Y-%m-%d")
        clean_title = re.sub(r"[^\w\-_]", "_", announcement.title)
        filename = f"{date_str}_{clean_title}.pdf"
        dest = self.output_dir / filename

        response = await context.request.get(
            announcement.pdf_url,
            headers={"Referer": self.source_url},
        )

        if not response.ok:
            raise Exception(f"Failed to download PDF: {response.status} {response.status_text}")
        
        content_type = response.headers.get("Content-Type", "")

        if "pdf" not in content_type.lower():
            print(f"[BHP] Warning: URL {announcement.pdf_url} did not return a PDF (Content-Type: {content_type})")

        dest.write_bytes(await response.body())
        print(f"[BHP] Saved: {dest}")
        return dest

    async def download_pdf(self, announcement: Announcement) -> Path:
        if announcement.local_path:
            return announcement.local_path
        
        raise NotImplementedError(
            "BHP downloads are handled inside fetch_announcements via browser context"
        )
    
    async def scrape(self) -> list[Announcement]:
        return await self.fetch_announcements()