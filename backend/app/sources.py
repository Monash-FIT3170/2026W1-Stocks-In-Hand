"""Small, shared catalogue of the ASX sources enabled in the AWS pipeline."""

from dataclasses import dataclass
from typing import Literal

SourceAdapter = Literal[
    "anz",
    "bhp",
    "cba",
    "coh",
    "col",
    "csl",
    "mqg",
    "org",
    "rio",
    "tcl",
    "tls",
    "wds",
    "wes",
]


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
    "COH": SourceDefinition(
        ticker="COH",
        adapter="coh",
        source_url=(
            "https://www.cochlear.com/au/en/corporate/investors/"
            "asx-announcements"
        ),
    ),
    "COL": SourceDefinition(
        ticker="COL",
        adapter="col",
        source_url=(
            "https://www.colesgroup.com.au/investors/?page=asx-announcements"
        ),
    ),
    "CSL": SourceDefinition(
        ticker="CSL",
        adapter="csl",
        source_url="https://investors.csl.com/investors/asx-announcements",
    ),
    "MQG": SourceDefinition(
        ticker="MQG",
        adapter="mqg",
        source_url="https://www.macquarie.com/au/en/investors/reports.html",
    ),
    "ORG": SourceDefinition(
        ticker="ORG",
        adapter="org",
        source_url=(
            "https://www.originenergy.com.au/about/investors-media/"
            "media-releases/"
        ),
    ),
    "RIO": SourceDefinition(
        ticker="RIO",
        adapter="rio",
        source_url="https://www.riotinto.com/en/invest/exchange-releases",
    ),
    "TCL": SourceDefinition(
        ticker="TCL",
        adapter="tcl",
        source_url=(
            "https://www.transurban.com/investor-centre/asx-releases.html"
        ),
    ),
    "TLS": SourceDefinition(
        ticker="TLS",
        adapter="tls",
        source_url="https://www.telstra.com.au/aboutus/investors/announcements",
    ),
    "WDS": SourceDefinition(
        ticker="WDS",
        adapter="wds",
        source_url="https://www.woodside.com/media-centre/announcements",
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
