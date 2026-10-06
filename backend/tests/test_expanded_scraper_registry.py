"""Every ticker in the catalogue has a scraper for its source adapter."""

import pytest

from app.sources import SOURCES
from scrapers.registry import REGISTRY, SCRAPERS, get_scraper


@pytest.mark.parametrize("ticker", sorted(SOURCES))
def test_every_catalogue_ticker_has_an_instantiable_scraper(ticker: str) -> None:
    scraper = get_scraper(f"{ticker.lower()}.ax")

    assert type(scraper) is SCRAPERS[SOURCES[ticker].adapter]
    assert scraper.ticker == ticker


def test_registry_covers_exactly_the_catalogue() -> None:
    assert set(REGISTRY) == set(SOURCES)


def test_unknown_ticker_has_no_scraper() -> None:
    with pytest.raises(ValueError, match="No scraper implemented for 'XYZ'"):
        get_scraper("xyz")
