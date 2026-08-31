import re
from datetime import datetime
from urllib.parse import urljoin

import httpx
from playwright.async_api import Error as PlaywrightError, async_playwright

from app.services.title_normalization import normalise_title
from ..base import BaseScraper, Announcement
from ..browser import chromium_launch_options


def clean_bhp_title(raw_title: str, article_url: str) -> str:
    """Retain the BHP-specific entry point while using shared title cleanup."""
    return normalise_title(raw_title, article_url)


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
                **chromium_launch_options(extra_args=("--disable-http2",))
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

            try:
                await page.goto(
                    self.source_url,
                    # BHP currently keeps some page resources open
                    # indefinitely; the committed HTML is enough for links.
                    wait_until="commit",
                    timeout=30_000,
                )
            except PlaywrightError:
                # Some Chromium/AWS networks fail BHP's HTTP/2 negotiation
                # even though the same public page works over HTTP/1.1.
                await page.close()
                page = await context.new_page()
                async with httpx.AsyncClient(
                    timeout=30.0,
                    headers={"User-Agent": "Mozilla/5.0"},
                ) as client:
                    response = await client.get(self.source_url)
                    response.raise_for_status()
                static_html = re.sub(
                    r"<script\b[^>]*>.*?</script>",
                    "",
                    response.text,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                await page.set_content(
                    static_html,
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )

            await page.wait_for_timeout(3000)

            article_links = await self._extract_article_links(page)

            print(f"[BHP] Found {len(article_links)} article links")

            # Resolving each article to its final document is downloader work.
            # Queue B carries the stable article URL so discovery remains fast
            # and performs no document requests.
            for item in article_links:
                announcements.append(
                    Announcement(
                        ticker=self.ticker,
                        title=item["title"],
                        date=item["date"],
                        pdf_url=item["article_url"],
                        source_url=self.source_url,
                        metadata={
                            "article_url": item["article_url"],
                            "source_id": item["article_url"],
                        },
                    )
                )

            announcements = self._dedupe_announcements(announcements)

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
            title = clean_bhp_title(text, full_url)

            if not self._looks_like_bhp_article(full_url, title):
                continue

            date = await self._extract_nearby_date(link)

            if not date:
                print(f"[BHP] Skipping article because no date found: {title}")
                continue

            items.append(
                {
                    "title": title,
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

    def _dedupe_article_links(self, items: list[dict]) -> list[dict]:
        seen: set[str] = set()
        result = []
        for item in items:
            key = item["article_url"]
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def _dedupe_announcements(self, announcements: list) -> list:
        seen: set[str] = set()
        result = []
        for ann in announcements:
            key = ann.pdf_url or ann.source_url or ann.title
            if key not in seen:
                seen.add(key)
                result.append(ann)
        return result

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
