"""Every catalogue ticker's source adapter.

The ticker catalogue (``app.sources.SOURCES``) names each company's adapter.
Discovery lists documents through ``adapter_for(ticker)`` and download
fetches them through ``adapter_named(message.source_adapter)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.sources import SOURCES, AdapterName, SourceDefinition, normalise_symbol

from .adapter import DocumentRequest, SourceAdapter
from .base import Announcement, BaseScraper
from .companies.anz import ANZScraper
from .companies.bhp import BHPScraper
from .companies.cba import CBAScraper
from .companies.coh import COHScraper
from .companies.col import COLScraper
from .companies.csl import CSLScraper
from .companies.mqg import MQGScraper
from .companies.org import ORGScraper
from .companies.rio import RIOScraper
from .companies.tcl import TCLScraper
from .companies.tls import TLSScraper
from .companies.wds import WDSScraper
from .companies.wes import WESScraper

if TYPE_CHECKING:
    from lambdas.download_validation import DownloadedDocument


class ScraperAdapter(SourceAdapter):
    """A source adapter made of a discovery scraper and the shared resolver.

    Compatibility wrapper while each company's listing and download code
    moves into one adapter.
    """

    def __init__(self, source: SourceDefinition, scraper: type[BaseScraper]) -> None:
        super().__init__(source)
        self.scraper = scraper

    async def list_documents(self) -> list[Announcement]:
        return await self.scraper().fetch_announcements()

    async def fetch_document(
        self,
        request: DocumentRequest,
        *,
        max_bytes: int,
    ) -> DownloadedDocument:
        from lambdas.source_download import fetch_document

        return await fetch_document(
            source_adapter=self.source.adapter,
            source_url=self.source_url,
            document_url=request.document_url,
            title=request.title,
            metadata=request.metadata,
            max_bytes=max_bytes,
        )


_SCRAPERS: dict[AdapterName, type[BaseScraper]] = {
    "anz": ANZScraper,
    "bhp": BHPScraper,
    "cba": CBAScraper,
    "coh": COHScraper,
    "col": COLScraper,
    "csl": CSLScraper,
    "mqg": MQGScraper,
    "org": ORGScraper,
    "rio": RIOScraper,
    "tcl": TCLScraper,
    "tls": TLSScraper,
    "wds": WDSScraper,
    "wes": WESScraper,
}

ADAPTERS: dict[AdapterName, SourceAdapter] = {
    source.adapter: ScraperAdapter(source, _SCRAPERS[source.adapter])
    for source in SOURCES.values()
}


def adapter_for(ticker: str) -> SourceAdapter:
    symbol = normalise_symbol(ticker)
    source = SOURCES.get(symbol)
    if source is None:
        raise ValueError(
            f"No source adapter for '{symbol}'. Available: {list(SOURCES)}"
        )
    return ADAPTERS[source.adapter]


def adapter_named(name: str) -> SourceAdapter:
    try:
        return ADAPTERS[name]  # type: ignore[index]
    except KeyError:
        raise ValueError(f"No source adapter named '{name}'") from None


async def discover(ticker: str) -> list[Announcement]:
    """Discover announcement metadata without downloading or writing files."""
    return await adapter_for(ticker).list_documents()
