from datetime import datetime
import re

import httpx

from ..base import BaseScraper, Announcement

YOURIR_BASE = (
    "https://yourir.info/resources/4d216b570d08af30/announcements/anz.asx"
)
YOURIR_FEED = "https://yourir.info/api/v5/symbols/anz.asx/announcements"
YOURIR_APP_ID = "4d216b570d08af30"


class ANZScraper(BaseScraper):

    @property
    def ticker(self) -> str:
        return "ANZ"

    @property
    def source_url(self) -> str:
        return "https://www.anz.com/shareholder/centre/investor-toolkit/asx-announcements/"

    async def fetch_announcements(self) -> list[Announcement]:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(20.0),
            headers={
                "Accept": "application/json",
                "Referer": "https://www.anz.com/",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
        ) as client:
            response = await client.get(
                YOURIR_FEED,
                params={
                    "appID": YOURIR_APP_ID,
                    "includeEmbargoed": 1,
                    "includeOtherIssuers": 0,
                    "includeRetracted": 0,
                    "liveness": "live",
                    "order": "desc",
                    "page": 1,
                    "pageSize": 20,
                    "priceSensitiveOnly": 0,
                    "range": "all",
                },
            )
            response.raise_for_status()
            return self._parse_feed(response.json())

    def _parse_feed(self, payload: object) -> list[Announcement]:
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), dict):
            raise ValueError("YourIR announcement feed is missing items")

        items = payload["items"]
        headings = items.get("heading")
        published_times = items.get("time")
        file_ids = items.get("fileID")
        if not all(isinstance(values, list) for values in (headings, published_times, file_ids)):
            raise ValueError("YourIR announcement feed has an invalid item schema")

        announcements: list[Announcement] = []
        for title, published_at, yourir_id in zip(
            headings,
            published_times,
            file_ids,
            strict=False,
        ):
            if not all(isinstance(value, str) and value.strip() for value in (title, published_at, yourir_id)):
                continue
            date = datetime.strptime(published_at[:10], "%Y-%m-%d")
            announcements.append(
                Announcement(
                    ticker=self.ticker,
                    title=title,
                    date=date,
                    pdf_url=self._build_pdf_url(yourir_id, title),
                    source_url=self.source_url,
                    metadata={
                        "yourir_id": yourir_id,
                        "source_id": yourir_id,
                    },
                )
            )
        return announcements

    def _build_pdf_url(self, yourir_id: str, title: str) -> str:
        filename = re.sub(r"[^\w\s]", "", title)
        filename = re.sub(r"\s+", "_", filename.strip())
        filename = f"ANZ_{filename}.pdf"
        return f"{YOURIR_BASE}/{yourir_id}/{filename}"
