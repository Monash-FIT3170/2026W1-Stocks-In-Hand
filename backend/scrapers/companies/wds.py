import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright, BrowserContext

from ..base import BaseScraper, Announcement


class WDSScraper(BaseScraper):
    """
    Woodside Energy Group (WDS) scraper.

    Source is a Sitefinity DX site. The "Recent announcements" list on
    /media-centre/announcements is populated client-side, and the page
    supports pagination via a `?pageNo=N` query string (confirmed by the
    "Announcements" nav link resolving to .../announcements1 -> pageNo=1).

    PDFs are served as static assets under a predictable path:
        https://www.woodside.com/docs/default-source/asx-announcements/<year>/<slug>.pdf?sfvrsn=...
    Some listing rows may link straight to that PDF; others may link to an
    interstitial detail page that embeds the PDF (same shape as BHP). Both
    cases are handled below rather than assumed.
    """

    # How many `?pageNo=` pages to walk before stopping. Kept small since
    # this mirrors the "recent announcements" scope every other scraper in
    # this repo uses — bump this if a deeper backfill is ever needed.
    MAX_PAGES = 2

    @property
    def ticker(self) -> str:
        return "WDS"

    @property
    def source_url(self) -> str:
        return "https://www.woodside.com/media-centre/announcements"

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

            article_links: list[dict] = []

            for page_no in range(1, self.MAX_PAGES + 1):
                page_url = (
                    self.source_url
                    if page_no == 1
                    else f"{self.source_url}?pageNo={page_no}"
                )

                page = await context.new_page()
                try:
                    await page.goto(
                        page_url,
                        wait_until="networkidle",
                        timeout=60000,
                    )
                except Exception as e:
                    print(f"[WDS] Failed to load page {page_no} ({page_url}): {e}")
                    await page.close()
                    break

                # The list renders after an async fetch; give it a beat and
                # then wait for at least one plausible announcement link.
                try:
                    await page.wait_for_selector(
                        "a[href*='.pdf'], a[href*='/media-centre/announcements/']",
                        timeout=15000,
                    )
                except Exception:
                    pass

                await page.wait_for_timeout(1500)

                page_items = await self._extract_article_links(page, page_url)
                await page.close()

                new_items = [
                    item
                    for item in page_items
                    if item["article_url"] not in {a["article_url"] for a in article_links}
                ]

                print(f"[WDS] Page {page_no}: found {len(page_items)} candidate links, {len(new_items)} new")

                if not new_items:
                    break

                article_links.extend(new_items)

            for item in article_links:
                try:
                    pdf_url = await self._resolve_pdf_url(context, item["article_url"])

                    if not pdf_url:
                        print(f"[WDS] No PDF found for: {item['title']}")
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
                                "raw_date": item["raw_date"],
                            },
                        )
                    )
                except Exception as e:
                    print(f"[WDS] Failed to process link {item['article_url']}: {e}")

            announcements = self._dedupe_announcements(announcements)

            for ann in announcements:
                try:
                    ann.local_path = await self._download_via_browser(context, ann)
                except Exception as e:
                    print(f"[WDS] Failed to download '{ann.title}': {e}")

            await browser.close()

        return announcements

    async def _extract_article_links(self, page, page_url: str) -> list[dict]:
        items = []

        links = await page.query_selector_all("a[href]")

        for link in links:
            href = await link.get_attribute("href")
            text = (await link.inner_text()).strip()

            if not href:
                continue

            full_url = urljoin(page_url, href)

            if not self._looks_like_wds_announcement(full_url, text):
                continue

            title = text or self._title_from_url(full_url)
            date = await self._extract_nearby_date(link)

            if not date:
                print(f"[WDS] Skipping link because no date found nearby: {title}")
                continue

            items.append(
                {
                    "title": title,
                    "date": date,
                    "raw_date": date.isoformat(),
                    "article_url": full_url,
                }
            )

        return self._dedupe_article_links(items)

    def _looks_like_wds_announcement(self, url: str, text: str) -> bool:
        url_lower = url.lower()

        if url_lower.startswith("http") and "woodside.com" not in url_lower:
            return False

        if url_lower.split("?", 1)[0].endswith(".pdf"):
            return True

        if "/media-centre/announcements/" in url_lower and url_lower.rstrip("/") != self.source_url.lower():
            return True

        return False

    def _title_from_url(self, url: str) -> str:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        slug = slug.split("?", 1)[0]
        slug = re.sub(r"\.pdf$", "", slug, flags=re.IGNORECASE)
        slug = re.sub(r"^\d+[-_]", "", slug)  # strip leading "017-" style prefixes
        return slug.replace("-", " ").replace("_", " ").strip().title() or "Announcement"

    async def _resolve_pdf_url(self, context: BrowserContext, article_url: str) -> str | None:
        if article_url.lower().split("?", 1)[0].endswith(".pdf"):
            return article_url

        page = await context.new_page()
        try:
            await page.goto(article_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)

            pdf_links = await page.query_selector_all("a[href*='.pdf']")
            for link in pdf_links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                full_url = urljoin(article_url, href)
                if ".pdf" in full_url.lower():
                    return full_url

            html = await page.content()
            match = re.search(r'https?://[^"\']+\.pdf(?:\?[^"\']*)?', html)
            if match:
                return match.group(0)

            relative_match = re.search(r'["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html)
            if relative_match:
                return urljoin(article_url, relative_match.group(1))

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
        Walk up the DOM from the announcement link looking for a date.

        The exact row markup isn't known ahead of time, so rather than bet
        on one CSS selector (which can return a wrapper div tight enough to
        exclude the date entirely — an earlier version of this method had
        exactly that bug), this checks each ancestor level individually,
        narrowest first, and stops at the first level whose own text
        contains a date. Since a parent's innerText already includes
        everything nested inside it, the *narrowest* matching level is by
        construction the smallest container that has both the title and a
        date in it — which keeps a multi-row list wrapper (with several
        rows' worth of dates) from ever being consulted, so we can't
        accidentally return a neighbouring row's date. It also prefers a
        semantic <time datetime="..."> attribute if one exists in that
        vicinity, since that's unambiguous where present.

        Levels wider than ~2000 chars are treated as having left the
        row/card and entered a section or page wrapper, and are not
        searched.
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
            r"\d{1,2}\s+[A-Za-z]+\s+\d{4}",  # 16 March 2026
            r"\d{1,2}/\d{1,2}/\d{4}",        # 16/03/2026
            r"\d{1,2}\.\d{1,2}\.\d{2}\b",    # 16.03.26
            r"\d{4}-\d{2}-\d{2}",            # 2026-03-16
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
            "%d %B %Y",
            "%d %b %Y",
            "%d/%m/%Y",
            "%d.%m.%y",
        ):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # Tolerate full ISO-8601 timestamps (e.g. "2026-06-25T02:00:00.000Z")
        # in case a <time datetime="..."> attribute isn't pre-trimmed.
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
            headers={"Referer": self.source_url},
        )

        if not response.ok:
            raise RuntimeError(f"HTTP {response.status} for {announcement.pdf_url}")

        body = await response.body()

        if body[:4] != b"%PDF":
            raise ValueError(f"Downloaded file is not a PDF: {announcement.pdf_url}")

        dest.write_bytes(body)
        print(f"[WDS] Saved: {dest}")
        return dest

    async def download_pdf(self, announcement: Announcement) -> Path:
        if announcement.local_path:
            return announcement.local_path

        raise NotImplementedError(
            "WDS downloads are handled inside fetch_announcements via browser context"
        )

    async def scrape(self) -> list[Announcement]:
        return await self.fetch_announcements()
