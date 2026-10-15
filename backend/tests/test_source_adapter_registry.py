"""Every ticker in the catalogue has a source adapter."""

import pytest

from app.sources import SOURCES
from scrapers.registry import ADAPTERS, adapter_for, adapter_named


@pytest.mark.parametrize("ticker", sorted(SOURCES))
def test_every_catalogue_ticker_has_its_source_adapter(ticker: str) -> None:
    adapter = adapter_for(f"{ticker.lower()}.ax")

    assert adapter is adapter_named(SOURCES[ticker].adapter)
    assert adapter.ticker == ticker
    assert adapter.source_url == SOURCES[ticker].source_url


def test_adapters_cover_exactly_the_catalogue() -> None:
    assert set(ADAPTERS) == {source.adapter for source in SOURCES.values()}


def test_unknown_ticker_or_adapter_has_none() -> None:
    with pytest.raises(ValueError, match="No source adapter for 'XYZ'"):
        adapter_for("xyz")
    with pytest.raises(ValueError, match="No source adapter named 'xyz'"):
        adapter_named("xyz")
