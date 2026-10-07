from app.sources import SOURCES, SourceAdapter, normalise_symbol

from .base import BaseScraper, Announcement
from .companies.anz import ANZScraper
from .companies.csl import CSLScraper
from .companies.bhp import BHPScraper
from .companies.cba import CBAScraper
from .companies.col import COLScraper
from .companies.coh import COHScraper
from .companies.tcl import TCLScraper
from .companies.tls import TLSScraper
from .companies.wes import WESScraper
from .companies.wds import WDSScraper
from .companies.rio import RIOScraper
from .companies.org import ORGScraper
from .companies.mqg import MQGScraper

# One scraper per source adapter. The ticker catalogue (app.sources.SOURCES)
# names each company's adapter, so onboarding a company means one catalogue
# entry plus its adapter here.
SCRAPERS: dict[SourceAdapter, type[BaseScraper]] = {
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

_missing_scrapers = sorted({source.adapter for source in SOURCES.values()} - set(SCRAPERS))
if _missing_scrapers:
    raise RuntimeError(
        "The ticker catalogue names source adapters with no scraper: "
        f"{_missing_scrapers}"
    )

REGISTRY: dict[str, type[BaseScraper]] = {
    ticker: SCRAPERS[source.adapter] for ticker, source in SOURCES.items()
}


def get_scraper(ticker: str) -> BaseScraper:
    symbol = normalise_symbol(ticker)
    scraper_type = REGISTRY.get(symbol)
    if scraper_type is None:
        raise ValueError(
            f"No scraper implemented for '{symbol}'. "
            f"Available: {list(REGISTRY.keys())}"
        )
    return scraper_type()


async def discover(ticker: str) -> list[Announcement]:
    """Discover announcement metadata without downloading or writing files."""
    return await get_scraper(ticker).fetch_announcements()


def available_tickers() -> list[str]:
    return list(REGISTRY.keys())
