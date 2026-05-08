import re
import httpx
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page

from ..base import BaseScraper, Announcement



class BHPScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "BHP"

    @property
    def source_url(self) -> str:
        return "https://www.bhp.com/investor-hub/market-announcements"  # IR page URL when you get to it

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

            page_text = await page.inner_text("body")

            if "technical issues" in page_text.lower():
                print("[BHP] Market announcements page is currently unavailable")
                await browser.close()
                return announcements
            
            await page.wait_for_selector("a[href*='.pdf'], a[href*='/news/'], a[href*='/investor']")

            links = await page.query_selector_all("a")

            for link in links:
                href = await link.get_attribute("href")
                text = (await link.inner_text()).strip()

                if not href or not text:
                    continue

                if not self._looks_like_announcement(href, text):
                    continue

                full_url = urljoin(self.source_url, href)

                date = await self._extract_nearby_date(link)

                if not date:
                    print(f"[BHP] Skipping '{text}' because no date was found")
                    continue

                announcements.append(
                    Announcement(
                        ticker=self.ticker,
                        title=text,
                        date=date,
                        pdf_url=full_url,
                        source_url=self.source_url,
                        metadata={"raw_href: href}"},
                    )
                )

            for ann in announcements:
                try:
                    ann.local_path = await self._download_via_browser(context, ann)
                except Exception as e:
                    print(f"[BHP] Failed to download '{ann.title}': {e}")

            await browser.close()

        return announcements
    
    def _looks_like_announcement(self, href: str, text: str) -> bool:
        href_lower = href.lower()
        text_lower = text.lower()

        useful_keywords = [
            "announcement",
            "appendix",
            "annual report",
            "quarterly",
            "results",
            "presentation",
            "dividend",
            "notice",
            "market",
            "asx",
        ]

        if ".pdf" in href_lower:
            return True
        
        return any(keyword in text_lower or keyword in href_lower for keyword in useful_keywords)
    
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