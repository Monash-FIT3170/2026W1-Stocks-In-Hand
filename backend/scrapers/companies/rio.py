import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright, BrowserContext

from ..base import BaseScraper, Announcement
from ..browser import chromium_launch_options


class RIOScraper(BaseScraper):
    """
    Rio Tinto Group (RIO) scraper.

    riotinto.com itself doesn't host a page listing routine ASX filings —
    the "Invest" hub links to /en/invest/exchange-releases, which in turn
    delegates that whole feed to a third-party IR distributor, Euroland
    (tools.eurolandir.com). That page shows three tabs (LSE/RNS, ASX, SEC),
    each backed by a Euroland widget URL differing only by a `v=` query
    param; the ASX one (companycode=uk-rio, v=asx2023) is the equivalent of
    what every other scraper in this repo treats as "the announcements
    page". Individual releases live at fixed URLs of the shape
    /tools/PressReleases/GetPressRelease/?ID=<id>&companycode=...

    The Euroland widget renders its release table client-side (there's a
    visible "No Data Available" placeholder in the pre-JS markup, plus
    javascript: hrefs like `PR.loadYearsData(2026)` for its year filter),
    so — same as BHP/WDS — rows are discovered defensively by scanning for
    `GetPressRelease` links rather than by betting on an exact CSS class.

    To sidestep iframe cross-frame complexity entirely, this navigates
    directly to the resolved Euroland URL as its own top-level page (that
    URL renders as a complete standalone page, not just an embeddable
    fragment) instead of trying to reach into an <iframe> on the
    riotinto.com wrapper page.
    """

    EXCHANGE_RELEASES_URL = "https://www.riotinto.com/en/invest/exchange-releases"

    # Confirmed by loading /en/invest/exchange-releases directly: the ASX
    # tab is backed by this Euroland widget URL. Used as a fallback if the
    # wrapper page's markup can't be parsed for the live iframe src (e.g.
    # Rio rotates the `v=` revision string).
    FALLBACK_ASX_FEED_URL = (
        "https://tools.eurolandir.com/tools/pressreleases/"
        "?companycode=uk-rio&v=asx2023&lang=en-GB"
    )

    @property
    def ticker(self) -> str:
        return "RIO"

    @property
    def source_url(self) -> str:
        return self.EXCHANGE_RELEASES_URL

    async def fetch_announcements(self) -> list[Announcement]:
        announcements: list[Announcement] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(**chromium_launch_options())

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

            feed_url = await self._resolve_asx_feed_url(context)
            print(f"[RIO] Using ASX feed: {feed_url}")

            page = await context.new_page()
            try:
                await page.goto(feed_url, wait_until="networkidle", timeout=60000)
                await self._ensure_releases_loaded(page)
                article_links = await self._extract_release_links(page, feed_url)
            except Exception as e:
                print(f"[RIO] Failed to load release feed ({feed_url}): {e}")
                article_links = []
            finally:
                await page.close()

            print(f"[RIO] Found {len(article_links)} candidate releases")

            for item in article_links:
                try:
                    pdf_url = await self._resolve_pdf_url(context, item["article_url"])

                    if not pdf_url:
                        print(f"[RIO] No PDF found for: {item['title']}")
                        continue

                    announcements.append(
                        Announcement(
                            ticker=self.ticker,
                            title=item["title"],
                            date=item["date"],
                            pdf_url=pdf_url,
                            source_url=item["article_url"],
                            metadata={
                                "listing_url": feed_url,
                                "article_url": item["article_url"],
                                "raw_date": item["raw_date"],
                            },
                        )
                    )
                except Exception as e:
                    print(f"[RIO] Failed to process link {item['article_url']}: {e}")

            announcements = self._dedupe_announcements(announcements)

            await browser.close()

        return announcements

    async def _resolve_asx_feed_url(self, context: BrowserContext) -> str:
        """
        Read the live iframe src(s) off the exchange-releases wrapper page
        and pick the ASX one, falling back to the last-known-good URL if
        the page structure doesn't match what we expect.
        """
        page = await context.new_page()
        try:
            await page.goto(self.EXCHANGE_RELEASES_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)

            frames = await page.query_selector_all("iframe[src*='eurolandir.com']")
            candidates = []
            for frame in frames:
                src = await frame.get_attribute("src")
                if src:
                    candidates.append(urljoin(self.EXCHANGE_RELEASES_URL, src))

            for url in candidates:
                if "v=asx" in url.lower():
                    return url

            # Also check plain <a> links in case the tabs aren't iframes
            # in the current markup.
            links = await page.query_selector_all("a[href*='eurolandir.com']")
            for link in links:
                href = await link.get_attribute("href")
                if href and "v=asx" in href.lower():
                    return urljoin(self.EXCHANGE_RELEASES_URL, href)

            if candidates:
                print(f"[RIO] No ASX-tagged eurolandir URL found, falling back to default")
            return self.FALLBACK_ASX_FEED_URL
        except Exception as e:
            print(f"[RIO] Failed to resolve ASX feed URL from wrapper page: {e}")
            return self.FALLBACK_ASX_FEED_URL
        finally:
            await page.close()

    async def _ensure_releases_loaded(self, page) -> None:
        """
        The widget's table is populated by client-side JS. Give it a beat,
        and if nothing's rendered yet, explicitly click the current-year
        filter (falling back to "All") the same way a visitor would.
        """
        try:
            await page.wait_for_selector("a[href*='GetPressRelease']", timeout=8000)
            return
        except Exception:
            pass

        current_year = str(datetime.now().year)
        year_link = await page.query_selector(f"a:text-is('{current_year}')")
        if not year_link:
            year_link = await page.query_selector("a[href*='loadAllPeriods']")

        if year_link:
            try:
                await year_link.click()
                await page.wait_for_timeout(2000)
                await page.wait_for_selector("a[href*='GetPressRelease']", timeout=15000)
            except Exception as e:
                print(f"[RIO] Releases list never populated after triggering load: {e}")

    async def _extract_release_links(self, page, page_url: str) -> list[dict]:
        items = []

        links = await page.query_selector_all("a[href*='GetPressRelease']")

        for link in links:
            href = await link.get_attribute("href")
            text = (await link.inner_text()).strip()

            if not href or not text:
                continue

            full_url = urljoin(page_url, href)
            date = await self._extract_nearby_date(link)

            if not date:
                print(f"[RIO] Skipping link because no date found nearby: {text}")
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

    async def _resolve_pdf_url(self, context: BrowserContext, article_url: str) -> str | None:
        page = await context.new_page()
        try:
            await page.goto(article_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1000)

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
        Same narrowest-ancestor-first climb used by the WDS scraper: check
        each ancestor level's own text, nearest first, and stop at the
        first level that contains a date. A parent's innerText already
        includes everything nested inside it, so the narrowest matching
        level is the smallest container holding both the title and its
        date — which keeps a wider multi-row table body from ever being
        consulted and misattributing a neighbouring row's date.
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
            r"\d{1,2}\s+[A-Za-z]+\s+\d{4}",  # 29 July 2026
            r"\d{1,2}/\d{1,2}/\d{4}",        # 29/07/2026
            r"\d{1,2}\.\d{1,2}\.\d{2}\b",    # 29.07.26
            r"\d{4}-\d{2}-\d{2}",            # 2026-07-29
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

        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _download_via_browser(
        self, context: BrowserContext, announcement: Announcement, referer: str
    ) -> Path:
        date_str = announcement.date.strftime("%Y-%m-%d")
        clean_title = re.sub(r"[^\w\-_]", "_", " ".join(announcement.title.split()))
        clean_title = clean_title[:120].strip("_") or "announcement"
        filename = f"{date_str}_{clean_title}.pdf"
        dest = self.output_dir / filename

        response = await context.request.get(
            announcement.pdf_url,
            headers={"Referer": referer},
        )

        if not response.ok:
            raise RuntimeError(f"HTTP {response.status} for {announcement.pdf_url}")

        body = await response.body()

        if body[:4] != b"%PDF":
            raise ValueError(f"Downloaded file is not a PDF: {announcement.pdf_url}")

        dest.write_bytes(body)
        print(f"[RIO] Saved: {dest}")
        return dest
