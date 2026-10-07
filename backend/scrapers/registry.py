"""Every catalogue ticker's source adapter.

The ticker catalogue (``app.sources.SOURCES``) names each company's adapter.
Discovery lists documents through ``adapter_for(ticker)`` and download
fetches them through ``adapter_named(message.source_adapter)``.
"""

from __future__ import annotations

from app.sources import SOURCES, AdapterName, normalise_symbol

from .adapter import SourceAdapter
from .base import Announcement
from .companies.anz import ANZAdapter
from .companies.bhp import BHPAdapter
from .companies.cba import CBAAdapter
from .companies.coh import COHAdapter
from .companies.col import COLAdapter
from .companies.csl import CSLAdapter
from .companies.mqg import MQGAdapter
from .companies.org import ORGAdapter
from .companies.rio import RIOAdapter
from .companies.tcl import TCLAdapter
from .companies.tls import TLSAdapter
from .companies.wds import WDSAdapter
from .companies.wes import WESAdapter

ADAPTER_TYPES: dict[AdapterName, type[SourceAdapter]] = {
    "anz": ANZAdapter,
    "bhp": BHPAdapter,
    "cba": CBAAdapter,
    "coh": COHAdapter,
    "col": COLAdapter,
    "csl": CSLAdapter,
    "mqg": MQGAdapter,
    "org": ORGAdapter,
    "rio": RIOAdapter,
    "tcl": TCLAdapter,
    "tls": TLSAdapter,
    "wds": WDSAdapter,
    "wes": WESAdapter,
}

ADAPTERS: dict[AdapterName, SourceAdapter] = {
    source.adapter: ADAPTER_TYPES[source.adapter](source) for source in SOURCES.values()
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
