import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import BrowserContext, async_playwright

from ..base import Announcement, BaseScraper
from ..browser import chromium_launch_options


class TCLScraper(BaseScraper):
    """Transurban (TCL) scraper using the YourIR API backing the ASX releases page."""

    APP_ID = "a50955429d255a58"
    SYMBOL = "tcl.asx"

    @property
    def ticker(self) -> str:
        return "TCL"

    @property
    def source_url(self) -> str:
        return "https://www.transurban.com/investor-centre/asx-releases.html"

    def _announcements_api_url(self) -> str:
        return f"https://yourir.info/api/v5/symbols/{self.SYMBOL}/announcements"

    def _announcement_api_url(self, file_id: str) -> str:
        return f"https://yourir.info/api/v5/symbols/{self.SYMBOL}/announcements/{file_id}"

    def _document_url(self, file_id: str) -> str:
        return f"{self._announcement_api_url(file_id)}/document"

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

            page = await context.new_page()
            await page.goto(self.source_url, wait_until="networkidle", timeout=120000)
            await page.wait_for_timeout(2000)

            rows = await self._fetch_rows_from_api(context)
            print(f"[TCL] Found {len(rows)} announcement rows")

            for row in rows:
                file_id = row["file_id"]
                heading = row["heading"]
                time_str = row["time"]

                parsed_date = self._parse_time(time_str)
                if not parsed_date:
                    print(f"[TCL] Could not parse date: {time_str}")
                    continue

                ann = Announcement(
                    ticker=self.ticker,
                    title=heading,
                    date=parsed_date,
                    pdf_url=self._document_url(file_id),
                    source_url=self.source_url,
                    metadata={
                        "listing_url": self.source_url,
                        "file_id": file_id,
                        "api_symbol": self.SYMBOL,
                        "raw_time": time_str,
                    },
                )

                announcements.append(ann)

            await browser.close()

        return self._dedupe_announcements(announcements)

    async def _fetch_rows_from_api(self, context: BrowserContext) -> list[dict[str, str]]:
        params = {
            "appID": self.APP_ID,
            "includeEmbargoed": "1",
            "includeOtherIssuers": "0",
            "includeRetracted": "0",
            "liveness": "live",
            "order": "desc",
            "page": "1",
            "pageSize": "15",
            "priceSensitiveOnly": "0",
            "range": "all",
        }

        response = await context.request.get(
            self._announcements_api_url(),
            params=params,
            headers={"Referer": self.source_url},
        )

        if not response.ok:
            raise RuntimeError(
                f"Failed to fetch TCL announcements list (HTTP {response.status})"
            )

        payload = await response.json()
        items = payload.get("items") or {}

        file_ids = items.get("fileID") or []
        headings = items.get("heading") or []
        times = items.get("time") or []

        row_count = min(len(file_ids), len(headings), len(times))

        rows: list[dict[str, str]] = []
        for i in range(row_count):
            file_id = str(file_ids[i]).strip()
            heading = re.sub(r"\s+", " ", str(headings[i]).strip())
            time_str = str(times[i]).strip()

            if not file_id or not heading or not time_str:
                continue

            rows.append(
                {
                    "file_id": file_id,
                    "heading": heading,
                    "time": time_str,
                }
            )

        return self._dedupe_rows(rows)

    def _parse_time(self, time_str: str) -> datetime | None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d %B %Y", "%d %b %Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                pass
        return None

    def _dedupe_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        result: list[dict[str, str]] = []

        for row in rows:
            key = row["file_id"]
            if key in seen:
                continue
            seen.add(key)
            result.append(row)

        return result

    def _dedupe_announcements(self, announcements: list[Announcement]) -> list[Announcement]:
        seen: set[str] = set()
        result: list[Announcement] = []

        for ann in announcements:
            file_id = (ann.metadata or {}).get("file_id")
            key = str(file_id or ann.pdf_url or ann.source_url or ann.title)
            if key in seen:
                continue
            seen.add(key)
            result.append(ann)

        return result

    async def _download_via_browser(self, context: BrowserContext, announcement: Announcement) -> Path:
        file_id = (announcement.metadata or {}).get("file_id")
        if not file_id:
            raise ValueError("Missing file_id for TCL announcement")

        date_str = announcement.date.strftime("%Y-%m-%d")
        clean_title = re.sub(r"[^\w-]", "_", " ".join(announcement.title.split()))
        clean_title = clean_title[:120].strip("_") or "announcement"
        filename = f"{date_str}_{clean_title}.pdf"
        dest = self.output_dir / filename

        response = await context.request.get(
            announcement.pdf_url,
            params={"appID": self.APP_ID, "liveness": "live"},
            headers={"Referer": self.source_url},
        )

        if not response.ok:
            raise RuntimeError(f"HTTP {response.status} for {announcement.pdf_url}")

        body = await response.body()
        dest.write_bytes(body)

        if not body.startswith(b"%PDF"):
            raise ValueError(f"Downloaded file is not a PDF: {announcement.pdf_url}")

        print(f"[TCL] Saved: {dest}")
        return dest
