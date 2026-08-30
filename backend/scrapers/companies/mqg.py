import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright, BrowserContext

from ..base import BaseScraper, Announcement


class MQGScraper(BaseScraper):
    """
    Macquarie Group (MQG) scraper.

    Note this is scoped to Macquarie's "Reports" page specifically (annual
    and half-year financial reports, per the page's own description) —
    Macquarie doesn't host a mirror of its routine ASX announcement feed
    at all; the investor hub's "Resources" section links straight out to
    the ASX's own company page for that. reports.html is what was asked
    for, so that's the scope here.

    The page is AEM-based (Adobe Experience Manager — visible from the
    `_jcr_content` asset paths) and populated by a client-side filter
    widget: the pre-JS markup literally contains "No results message" /
    "Service unavailable" placeholder strings for that widget, with no
    real rows. Each report resolves to a "microsite" detail page at
    /investors/reports/<slug>.html (e.g. full-year-2026.html — confirmed
    via search, not guessed), which in turn links to the actual PDF at
    /assets/macq/investor/reports/<year>/<slug>.pdf. A single detail page
    commonly links to that same PDF many times with different #page=N
    fragments (Directors' Report, Remuneration Report, ...) — fragments
    aren't sent in the actual HTTP request, so any of them resolves to an
    identical download; fragments are stripped before use here purely to
    keep the pdf_url/filename clean.

    Row discovery is defensive (broad anchor scan + URL-shape filtering)
    rather than betting on unverified widget CSS classes, same as the
    WDS/RIO/ORG scrapers.
    """

    LISTING_URL = "https://www.macquarie.com/au/en/investors/reports.html"

    @property
    def ticker(self) -> str:
        return "MQG"

    @property
    def source_url(self) -> str:
        return self.LISTING_URL

    async def fetch_announcements(self) -> list[Announcement]:
        announcements: list[Announcement] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--headless=new",
                ],
            )

            context = await browser.new_context(
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
            try:
                await page.goto(self.LISTING_URL, wait_until="networkidle", timeout=60000)
                try:
                    await page.wait_for_selector(
                        "a[href*='/investors/reports/'], a[href*='.pdf']",
                        timeout=15000,
                    )
                except Exception:
                    pass
                await page.wait_for_timeout(1000)
                article_links = await self._extract_report_links(page)
            except Exception as e:
                print(f"[MQG] Failed to load reports listing ({self.LISTING_URL}): {e}")
                article_links = []
            finally:
                await page.close()

            print(f"[MQG] Found {len(article_links)} candidate reports")

            for item in article_links:
                try:
                    pdf_url = await self._resolve_pdf_url(context, item["article_url"])

                    if not pdf_url:
                        print(f"[MQG] No PDF found for: {item['title']}")
                        continue

                    announcements.append(
                        Announcement(
                            ticker=self.ticker,
                            title=item["title"],
                            date=item["date"],
                            pdf_url=pdf_url,
                            source_url=item["article_url"],
                            metadata={
                                "listing_url": self.LISTING_URL,
                                "article_url": item["article_url"],
                                "raw_date": item["raw_date"],
                            },
                        )
                    )
                except Exception as e:
                    print(f"[MQG] Failed to process link {item['article_url']}: {e}")

            announcements = self._dedupe_announcements(announcements)

            await browser.close()

        return announcements

    async def _extract_report_links(self, page) -> list[dict]:
        items = []

        links = await page.query_selector_all("a[href]")

        for link in links:
            href = await link.get_attribute("href")
            text = (await link.inner_text()).strip()

            if not href:
                continue

            full_url = urljoin(self.LISTING_URL, href)

            if not self._looks_like_report_link(full_url, text):
                continue

            date = await self._extract_nearby_date(link)

            if not date:
                print(f"[MQG] Skipping link because no date found nearby: {text}")
                continue

            items.append(
                {
                    "title": text,
                    "date": date,
                    "raw_date": date.isoformat(),
                    "article_url": full_url,
                }
            )

        return self._dedupe_article_links(items)

    def _looks_like_report_link(self, url: str, text: str) -> bool:
        if not text:
            return False

        url_no_frag = url.split("#", 1)[0]
        url_lower = url_no_frag.lower()

        if url_lower.startswith("http") and "macquarie.com" not in url_lower:
            return False

        if url_lower.split("?", 1)[0].endswith(".pdf"):
            return True

        # A report "microsite" detail page, e.g.
        # /investors/reports/full-year-2026.html — but not the listing
        # page itself (/investors/reports.html has no extra path segment).
        if re.search(r"/investors/reports/[^/]+\.html$", url_lower.split("?", 1)[0]):
            return True

        return False

    async def _resolve_pdf_url(self, context: BrowserContext, article_url: str) -> str | None:
        article_no_frag = article_url.split("#", 1)[0]

        if article_no_frag.lower().split("?", 1)[0].endswith(".pdf"):
            return article_no_frag

        page = await context.new_page()
        try:
            await page.goto(article_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1000)

            pdf_links = await page.query_selector_all("a[href*='.pdf']")
            for link in pdf_links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                full_url = urljoin(article_url, href).split("#", 1)[0]
                if ".pdf" in full_url.lower():
                    return full_url

            html = await page.content()
            match = re.search(r'https?://[^"\']+\.pdf(?:\?[^"\']*)?', html)
            if match:
                return match.group(0).split("#", 1)[0]

            relative_match = re.search(r'["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html)
            if relative_match:
                return urljoin(article_url, relative_match.group(1)).split("#", 1)[0]

            return None
        finally:
            await page.close()

    def _dedupe_article_links(self, items: list[dict]) -> list[dict]:
        seen: set[str] = set()
        result = []
        for item in items:
            key = item["article_url"]
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def _dedupe_announcements(self, announcements: list[Announcement]) -> list[Announcement]:
        seen: set[str] = set()
        result = []
        for ann in announcements:
            key = ann.pdf_url or ann.source_url or ann.title
            if key not in seen:
                seen.add(key)
                result.append(ann)
        return result

    async def _extract_nearby_date(self, link) -> datetime | None:
        """
        Same narrowest-ancestor-first climb used by the WDS/RIO/ORG
        scrapers: check each ancestor level's own text, nearest first, and
        stop at the first level that contains a date, so a wider grid
        wrapper (with several reports' worth of text) is never consulted
        and can't hand back a neighbouring tile's date.
        """
        result = await link.evaluate(
            """
            el => {
                const levels = [];
                let node = el;
                let timeAttr = null;
                for (let i = 0; i < 8 && node && node.parentElement; i++) {
                    node = node.parentElement;
                    if (!timeAttr) {
                        const t = node.querySelector('time[datetime]');
                        if (t) timeAttr = t.getAttribute('datetime');
                    }
                    levels.push(node.innerText || '');
                }
                return { timeAttr, levels };
            }
            """
        )

        time_attr = (result or {}).get("timeAttr")
        if time_attr:
            parsed = self._parse_date_str(time_attr.strip()[:19].replace("T", " "))
            if parsed:
                return parsed

        for text in (result or {}).get("levels") or []:
            if len(text) > 2000:
                break
            parsed = self._first_date_in_text(text)
            if parsed:
                return parsed

        return None

    def _first_date_in_text(self, text: str) -> datetime | None:
        date_patterns = [
            r"[A-Za-z]+\s+\d{1,2},\s*\d{4}",  # July 31, 2026
            r"\d{1,2}\s+[A-Za-z]+\s+\d{4}",   # 31 July 2026
            r"\d{1,2}/\d{1,2}/\d{4}",         # 31/07/2026
            r"\d{1,2}\.\d{1,2}\.\d{2}\b",     # 31.07.26
            r"\d{4}-\d{2}-\d{2}",             # 2026-07-31
        ]

        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                parsed = self._parse_date_str(match.group(0))
                if parsed:
                    return parsed

        return None

    def _parse_date_str(self, date_str: str) -> datetime | None:
        date_str = date_str.strip()
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
            "%d/%m/%Y",
            "%d.%m.%y",
        ):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _download_via_browser(self, context: BrowserContext, announcement: Announcement) -> Path:
        date_str = announcement.date.strftime("%Y-%m-%d")
        clean_title = re.sub(r"[^\w\-_]", "_", " ".join(announcement.title.split()))
        clean_title = clean_title[:120].strip("_") or "announcement"
        filename = f"{date_str}_{clean_title}.pdf"
        dest = self.output_dir / filename

        response = await context.request.get(
            announcement.pdf_url,
            headers={"Referer": self.LISTING_URL},
        )

        if not response.ok:
            raise RuntimeError(f"HTTP {response.status} for {announcement.pdf_url}")

        body = await response.body()

        if body[:4] != b"%PDF":
            raise ValueError(f"Downloaded file is not a PDF: {announcement.pdf_url}")

        dest.write_bytes(body)
        print(f"[MQG] Saved: {dest}")
        return dest
