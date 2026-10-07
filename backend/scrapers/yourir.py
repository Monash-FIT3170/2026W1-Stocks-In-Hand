"""Source adapters for announcement feeds hosted by YourIR (yourir.info).

ANZ, CBA and TCL embed a YourIR widget on their investor pages. The widget
reads a JSON feed, so listing reads that feed over plain HTTP and download
fetches each document from YourIR directly; neither needs a browser. YourIR
refuses feed requests that do not come from the company's site, so each
company names the referer its own page sends.

How a company addresses its documents decides their identity, so it must
not change once documents are stored: ANZ and CBA link to YourIR's
resource files and identify a document by its YourIR file ID, while TCL
links to the feed's document endpoint and is identified by that URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from lambdas.common import PermanentDocumentError

from .adapter import DocumentRequest, SourceAdapter
from .base import Announcement

if TYPE_CHECKING:
    from lambdas.download_validation import DownloadedDocument

API_URL = "https://yourir.info/api/v5/symbols"
RESOURCES_URL = "https://yourir.info/resources"
YOURIR_HOST = "yourir.info"


@dataclass(frozen=True)
class YourIRFeed:
    symbol: str
    app_id: str
    # What the company's own page sends; YourIR rejects other requests.
    referer: str
    page_size: int
    include_other_issuers: bool
    documents: Literal["resource", "api"]
    # CBA's widget names a document "cba.asx/<file ID>", ANZ's "<file ID>".
    qualified_ids: bool = False

    @property
    def feed_url(self) -> str:
        return f"{API_URL}/{self.symbol}/announcements"

    @property
    def resources_url(self) -> str:
        return f"{RESOURCES_URL}/{self.app_id}/announcements"


class YourIRAdapter(SourceAdapter):
    feed: YourIRFeed

    async def list_documents(self) -> list[Announcement]:
        async with self.fetcher.session() as web:
            payload = await web.get_json(
            self.feed.feed_url,
                params={
                    "appID": self.feed.app_id,
                    "includeEmbargoed": 1,
                    "includeOtherIssuers": int(self.feed.include_other_issuers),
                    "includeRetracted": 0,
                    "liveness": "live",
                    "order": "desc",
                    "page": 1,
                    "pageSize": self.feed.page_size,
                    "priceSensitiveOnly": 0,
                    "range": "all",
                },
                headers={"Referer": self.feed.referer},
            )
        return [self._announcement(item) for item in feed_items(payload)]

    def _announcement(self, item: FeedItem) -> Announcement:
        if self.feed.documents == "api":
            return Announcement(
                ticker=self.ticker,
                title=item.heading,
                date=item.published_at,
                pdf_url=f"{self.feed.feed_url}/{item.file_id}/document",
                source_url=self.source_url,
                metadata={
                    "listing_url": self.source_url,
                    "file_id": item.file_id,
                    "api_symbol": self.feed.symbol,
                    "raw_time": item.local_time,
                },
            )
        yourir_id = (
            f"{self.feed.symbol}/{item.file_id}" if self.feed.qualified_ids else item.file_id
        )
        return Announcement(
            ticker=self.ticker,
            title=item.heading,
            date=item.published_at,
            pdf_url=self._resource_url(yourir_id, item.heading),
            source_url=self.source_url,
            metadata={"yourir_id": yourir_id, "source_id": yourir_id},
        )

    def _resource_url(self, yourir_id: str, title: str) -> str:
        base = self.feed.resources_url
        if not self.feed.qualified_ids:
            base = f"{base}/{self.feed.symbol}"
        filename = re.sub(r"\s+", "_", re.sub(r"[^\w\s]", "", title).strip())
        return f"{base}/{yourir_id}/{self.ticker}_{filename}.pdf"

    async def fetch_document(
        self,
        request: DocumentRequest,
        *,
        max_bytes: int,
    ) -> DownloadedDocument:
        async with self.fetcher.session() as web:
            if self.feed.documents == "api":
                return await web.download(
                    f"{request.document_url}?appID={self.feed.app_id}&liveness=live",
                    hosts=self.hosts,
                    referer=self.source_url,
                    max_bytes=max_bytes,
                )
            try:
                return await web.download(
                    request.document_url,
                    hosts=self.hosts,
                    referer=self.source_url,
                    max_bytes=max_bytes,
                )
            except PermanentDocumentError as exc:
                # YourIR also serves every resource under a fixed file name.
                yourir_id = request.metadata.get("yourir_id")
                if exc.code != "document_not_found" or not yourir_id:
                    raise
                return await web.download(
                    f"{self.feed.resources_url}/{yourir_id}/announcement.pdf",
                    hosts=self.hosts,
                    referer=self.source_url,
                    max_bytes=max_bytes,
                )


@dataclass(frozen=True)
class FeedItem:
    file_id: str
    heading: str
    published_at: datetime
    # The feed's Sydney-local "time", kept for TCL's metadata.
    local_time: str


def feed_items(payload: object) -> list[FeedItem]:
    """Read a YourIR announcement feed: parallel arrays, one entry per document."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), dict):
        raise ValueError("YourIR announcement feed is missing items")
    items = payload["items"]
    columns = [items.get(name) for name in ("fileID", "heading", "timestamp", "time")]
    if not all(isinstance(column, list) for column in columns):
        raise ValueError("YourIR announcement feed has an invalid item schema")

    parsed: list[FeedItem] = []
    seen: set[str] = set()
    for file_id, heading, timestamp, local_time in zip(*columns, strict=False):
        file_id = str(file_id or "").strip()
        heading = " ".join(str(heading or "").split())
        if not file_id or not heading or not isinstance(timestamp, int) or file_id in seen:
            continue
        seen.add(file_id)
        parsed.append(
            FeedItem(
                file_id=file_id,
                heading=heading,
                published_at=datetime.fromtimestamp(timestamp, timezone.utc),
                local_time=str(local_time or "").strip(),
            )
        )
    return parsed
