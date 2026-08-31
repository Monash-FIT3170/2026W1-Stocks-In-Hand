from pathlib import Path

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

# Add one import and one line here each time a new company is onboarded.
REGISTRY: dict[str, type[BaseScraper]] = {
    "ANZ": ANZScraper,
    "BHP": BHPScraper,
    "CBA": CBAScraper,
    "COL": COLScraper,
    "COH": COHScraper,
    "TCL": TCLScraper,
    "TLS": TLSScraper,
    "CSL": CSLScraper,
    "WES": WESScraper,
    "WDS": WDSScraper,
    "RIO": RIOScraper,
    "ORG": ORGScraper,
    "MQG": MQGScraper,
}


def get_scraper(ticker: str, output_dir: Path | None = None) -> BaseScraper:
    symbol = ticker.strip().upper()
    scraper_type = REGISTRY.get(symbol)
    if scraper_type is None:
        raise ValueError(
            f"No scraper implemented for '{symbol}'. "
            f"Available: {list(REGISTRY.keys())}"
        )
    return scraper_type(output_dir=output_dir)


async def discover(ticker: str) -> list[Announcement]:
    """Discover announcement metadata without downloading or writing files."""
    return await get_scraper(ticker).fetch_announcements()


async def scrape(ticker: str, output_dir: Path) -> list[Announcement]:
    """
    Public entrypoint for the entire ASX scraper module.
    When the higher-order platform system is built, this is the function it calls.

    Usage:
        results = await scrape("ANZ", Path("./output"))
    """
    return await get_scraper(ticker, output_dir).scrape()


def available_tickers() -> list[str]:
    return list(REGISTRY.keys())
