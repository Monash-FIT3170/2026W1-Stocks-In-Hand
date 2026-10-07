"""The source adapter interface: one company's announcements website.

A source adapter owns what the pipeline knows about one company's site: how
to list its recent documents (discovery) and how to fetch one of them
(download). Discovery records the adapter's resolution hints in each
Announcement's metadata, Queue B carries that metadata unchanged, and
download hands it back to the same adapter, so both halves of a company's
knowledge sit in one place.

Each adapter splits its work into a thin fetch step, which asks a web
session (``scrapers.fetching``) for pages, and a pure parse step over the
returned HTML or JSON, so parsing is tested against recorded pages.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from app.sources import SourceDefinition
from scrapers.base import Announcement
from scrapers.fetching import (
    Fetcher,
    LayoutChangedError,
    LiveFetcher,
    SourceUnreachableError,
)

__all__ = [
    "DocumentRequest",
    "LayoutChangedError",
    "SeededBrowserDownload",
    "SourceAdapter",
    "SourceUnreachableError",
]

if TYPE_CHECKING:
    from lambdas.download_validation import DownloadedDocument
    from scrapers.fetching import WebSession


@dataclass(frozen=True)
class DocumentRequest:
    """One discovered document, as download receives it on Queue B."""

    document_url: str
    title: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


class SourceAdapter(ABC):
    # Hosts this company's pages and documents may be fetched from.
    hosts: frozenset[str]

    def __init__(
        self,
        source: SourceDefinition,
        fetcher: Fetcher | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.source = source
        self.fetcher = fetcher or LiveFetcher()
        self.clock = clock

    @property
    def ticker(self) -> str:
        return self.source.ticker

    @property
    def source_url(self) -> str:
        return self.source.source_url

    async def list_documents(self) -> list[Announcement]:
        """List the company's recent documents without downloading any.

        Raises SourceUnreachableError when the site cannot be reached and
        LayoutChangedError when it answers with nothing this adapter can
        read, instead of reporting "no new documents".
        """
        listed = await self._list_documents()
        if not listed:
            raise LayoutChangedError(f"{self.ticker}'s listing had no documents to read")
        return listed

    @abstractmethod
    async def _list_documents(self) -> list[Announcement]:
        """Fetch and parse the listing; may return nothing."""

    @abstractmethod
    async def fetch_document(
        self,
        request: DocumentRequest,
        *,
        max_bytes: int,
    ) -> DownloadedDocument:
        """Download and validate one document this adapter listed."""

    def _validated(self, url: str) -> str:
        from lambdas.download_validation import validate_download_url

        return validate_download_url(url, hosts=self.hosts)


class SeededBrowserDownload:
    """Download through a browser session first seeded by a listing page.

    These sites only serve documents to a browser that has visited them, so
    download opens the page discovery found the document on (the feed,
    listing or article URL in its metadata) before requesting the document
    with that page as the referer.
    """

    session_options: Mapping[str, object] = {"disable_http2": True}

    async def fetch_document(
        self: SourceAdapter,  # type: ignore[misc]
        request: DocumentRequest,
        *,
        max_bytes: int,
    ) -> DownloadedDocument:
        document_url = self._validated(request.document_url)
        seed = self._validated(_seed_url(request.metadata) or self.source_url)
        async with self.fetcher.session(**self.session_options) as web:  # type: ignore[attr-defined]
            web: WebSession
            return await web.request_document(
                document_url,
                hosts=self.hosts,
                referer=seed,
                max_bytes=max_bytes,
                seed_url=seed,
            )


def _seed_url(metadata: Mapping[str, object]) -> str | None:
    # Prefer an HTML listing over an article URL: some sites (notably WDS)
    # list direct PDF links as their article URL, and opening a PDF as the
    # seed page starts a download instead of loading a page.
    for key in ("feed_url", "listing_url", "article_url"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None
