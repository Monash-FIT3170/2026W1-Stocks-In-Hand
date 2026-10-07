"""The source adapter interface: one company's announcements website.

A source adapter owns what the pipeline knows about one company's site: how
to list its recent documents (discovery) and how to fetch one of them
(download). Discovery records the adapter's resolution hints in each
Announcement's metadata, Queue B carries that metadata unchanged, and
download hands it back to the same adapter, so both halves of a company's
knowledge sit in one place.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.sources import SourceDefinition
from scrapers.base import Announcement

if TYPE_CHECKING:
    from lambdas.download_validation import DownloadedDocument


@dataclass(frozen=True)
class DocumentRequest:
    """One discovered document, as download receives it on Queue B."""

    document_url: str
    title: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


class SourceAdapter(ABC):
    def __init__(self, source: SourceDefinition) -> None:
        self.source = source

    @property
    def ticker(self) -> str:
        return self.source.ticker

    @property
    def source_url(self) -> str:
        return self.source.source_url

    @abstractmethod
    async def list_documents(self) -> list[Announcement]:
        """List the company's recent documents without downloading any."""

    @abstractmethod
    async def fetch_document(
        self,
        request: DocumentRequest,
        *,
        max_bytes: int,
    ) -> DownloadedDocument:
        """Download and validate one document this adapter listed."""
