from pathlib import Path

from .base import BaseScraper, Announcement
from .companies.anz import ANZScraper

# Add one import and one line here each time a new company is onboarded.
REGISTRY: dict[str, type[BaseScraper]] = {
    "ANZ": ANZScraper,
    # "BHP": BHPScraper,
    # "CSL": CSLScraper,
    # "CBA": CBAScraper,
    # "WES": WesScraper,
}


async def scrape(ticker: str, output_dir: Path) -> list[Announcement]:
    """
    Public entrypoint for the entire ASX scraper module.
    When the higher-order platform system is built, this is the function it calls.

    Usage:
        results = await scrape("ANZ", Path("./output"))
    """
    ticker = ticker.upper()
    if ticker not in REGISTRY:
        raise ValueError(
            f"No scraper implemented for '{ticker}'. "
            f"Available: {list(REGISTRY.keys())}"
        )
    scraper = REGISTRY[ticker](output_dir=output_dir)
    return await scraper.scrape()


def available_tickers() -> list[str]:
    return list(REGISTRY.keys())