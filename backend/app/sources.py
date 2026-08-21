"""Small, shared catalogue of the ASX sources enabled in the AWS pipeline."""

from dataclasses import dataclass
from typing import Literal

SourceAdapter = Literal["anz", "bhp", "cba", "csl", "wes"]


@dataclass(frozen=True)
class SourceDefinition:
    ticker: str
    adapter: SourceAdapter
    source_url: str


SOURCES: dict[str, SourceDefinition] = {
    "ANZ": SourceDefinition(
        ticker="ANZ",
        adapter="anz",
        source_url=(
            "https://www.anz.com/shareholder/centre/investor-toolkit/"
            "asx-announcements/"
        ),
    ),
    "BHP": SourceDefinition(
        ticker="BHP",
        adapter="bhp",
        source_url="https://www.bhp.com/investor-hub/market-announcements",
    ),
    "CBA": SourceDefinition(
        ticker="CBA",
        adapter="cba",
        source_url="https://www.commbank.com.au/about-us/investors/asx-announcements.html",
    ),
    "CSL": SourceDefinition(
        ticker="CSL",
        adapter="csl",
        source_url="https://investors.csl.com/investors/asx-announcements",
    ),
    "WES": SourceDefinition(
        ticker="WES",
        adapter="wes",
        source_url=(
            "https://www.wesfarmers.com.au/investor-centre/"
            "company-performance-news/asx-announcements"
        ),
    ),
}


def source_for_ticker(ticker: str) -> SourceDefinition | None:
    return SOURCES.get(ticker.strip().upper())


def adapter_matches_ticker(ticker: str, adapter: str) -> bool:
    source = source_for_ticker(ticker)
    return source is not None and source.adapter == adapter
