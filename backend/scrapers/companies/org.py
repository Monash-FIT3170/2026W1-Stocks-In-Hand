import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import async_playwright, BrowserContext

from ..base import BaseScraper, Announcement
from ..browser import chromium_launch_options


class ORGScraper(BaseScraper):
    """
    Origin Energy Limited (ORG) scraper.

    Unlike WDS/RIO, originenergy.com.au is a plain server-rendered
    WordPress site — the listing at /about/investors-media/media-releases/
    already contains every card's title, date, and article link with no
    client-side JS required, and paginates via `?query-0-page=N`. Each
    article page (e.g. .../quarterly-report-june-2026/) then links directly
    to one or more PDFs, e.g. "Quarterly Report June 2026 (PDF)" and
    "Quarterly Report June 2026 ASX/Media Release (PDF)" — when an article
    has more than one attachment, the one whose link text/href mentions
    "ASX" is preferred, since that's the actual lodged regulatory document
    rather than a supplementary report.

    Still uses Playwright (rather than plain httpx) for consistency with
    every other scraper in this repo, and because the exact WordPress
    theme's markup/classes weren't inspected live — row discovery is done
    defensively by scanning anchors and filtering by URL shape, same as
    WDS/RIO, rather than betting on unverified CSS selectors.
    """

    LISTING_BASE_URL = "https://www.originenergy.com.au/about/investors-media/media-releases/"

    # `?query-0-page=N` goes up to ~66 on the live site; kept small here to
    # mirror the "recent announcements" scope every other scraper uses.
    MAX_PAGES = 2

    @property
    def ticker(self) -> str:
        return "ORG"

    @property
    def source_url(self) -> str:
        return self.LISTING_BASE_URL

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

            article_links: list[dict] = []

            for page_no in range(1, self.MAX_PAGES + 1):
                page_url = (
                    self.LISTING_BASE_URL
                    if page_no == 1
                    else f"{self.LISTING_BASE_URL}?query-0-page={page_no}"
                )

                page = await context.new_page()
                try:
                    await page.goto(page_url, wait_until="networkidle", timeout=60000)
                except Exception as e:
                    print(f"[ORG] Failed to load page {page_no} ({page_url}): {e}")
                    await page.close()
                    break

                try:
                    await page.wait_for_selector(
                        "a[href*='/about/investors-media/']",
                        timeout=15000,
                    )
                except Exception:
                    pass

                page_items = await self._extract_article_links(page, page_url)
                await page.close()

                new_items = [
                    item
                    for item in page_items
                    if item["article_url"] not in {a["article_url"] for a in article_links}
                ]

                print(f"[ORG] Page {page_no}: found {len(page_items)} candidate links, {len(new_items)} new")

                if not new_items:
                    break

                article_links.extend(new_items)

            for item in article_links:
                try:
                    pdf_url = await self._resolve_pdf_url(context, item["article_url"])

                    if not pdf_url:
                        print(f"[ORG] No PDF found for: {item['title']}")
                        continue

                    announcements.append(
                        Announcement(
                            ticker=self.ticker,
                            title=item["title"],
                            date=item["date"],
                            pdf_url=pdf_url,
                            source_url=item["article_url"],
                            metadata={
                                "listing_url": self.LISTING_BASE_URL,
                                "article_url": item["article_url"],
                                "raw_date": item["raw_date"],
                            },
                        )
                    )
                except Exception as e:
                    print(f"[ORG] Failed to process link {item['article_url']}: {e}")

            announcements = self._dedupe_announcements(announcements)

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

            if not self._looks_like_org_release(full_url, text):
                continue

            date = await self._extract_nearby_date(link)

            if not date:
                print(f"[ORG] Skipping link because no date found nearby: {text}")
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

    def _looks_like_org_release(self, url: str, text: str) -> bool:
        url_lower = url.lower().split("#", 1)[0]

        if not text:
            return False

        if url_lower.startswith("http") and "originenergy.com.au" not in url_lower:
            return False

        if "/about/investors-media/" not in url_lower:
            return False

        # Exclude tag chips ("Asx", "Media Release", ...), pagination
        # controls, and the listing page linking to itself (e.g. a
        # breadcrumb back to "Media Releases").
        if "/tag/" in url_lower:
            return False

        if "query-0-page" in url_lower:
            return False

        if url_lower.rstrip("/") == self.LISTING_BASE_URL.lower().rstrip("/"):
            return False

        return True

    async def _resolve_pdf_url(self, context: BrowserContext, article_url: str) -> str | None:
        page = await context.new_page()
        try:
            await page.goto(article_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1000)

            pdf_links = await page.query_selector_all("a[href*='.pdf']")

            candidates: list[tuple[str, str]] = []  # (full_url, link_text)
            for link in pdf_links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                full_url = urljoin(article_url, href)
                if ".pdf" in full_url.lower():
                    text = (await link.inner_text()).strip()
                    candidates.append((full_url, text))

            if not candidates:
                html = await page.content()
                match = re.search(r'https?://[^"\']+\.pdf(?:\?[^"\']*)?', html)
                if match:
                    return match.group(0)

                relative_match = re.search(r'["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html)
                if relative_match:
                    return urljoin(article_url, relative_match.group(1))

                return None

            # An article can carry more than one attachment (e.g. a
            # standalone quarterly report plus the actual "ASX/Media
            # Release" PDF that was lodged with the exchange) — prefer
            # whichever one is explicitly ASX-labelled, since that's the
            # regulatory document, not a supplementary report.
            for full_url, text in candidates:
                if "asx" in text.lower() or "asx" in full_url.lower():
                    return full_url

            return candidates[0][0]
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
        Same narrowest-ancestor-first climb used by the WDS/RIO scrapers:
        check each ancestor level's own text, nearest first, and stop at
        the first level that contains a date, so a wider multi-card
        listing container is never consulted and can't hand back a
        neighbouring card's date.
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
            r"[A-Za-z]+\s+\d{1,2},\s*\d{4}",  # July 31, 2026 (listing page)
            r"\d{1,2}\s+[A-Za-z]+\s+\d{4}",   # 31 July 2026 (article page)
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
            headers={"Referer": self.LISTING_BASE_URL},
        )

        if not response.ok:
            raise RuntimeError(f"HTTP {response.status} for {announcement.pdf_url}")

        body = await response.body()

        if body[:4] != b"%PDF":
            raise ValueError(f"Downloaded file is not a PDF: {announcement.pdf_url}")

        dest.write_bytes(body)
        print(f"[ORG] Saved: {dest}")
        return dest
