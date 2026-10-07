"""The ticker catalogue: every ASX company the product supports.

Each entry owns one company's facts: its symbol, name, sector and industry,
the source adapter and announcements page the pipeline scrapes, and whether
the weekly schedule includes it by default. Every other list of tickers is
built from this one or checked against it (``tools/sync_tickers.py``).

Keep this module free of third-party imports: the queue-wiring CI job runs
tests that import it with only pytest and PyYAML installed.
"""

from dataclasses import dataclass
from typing import Literal

AdapterName = Literal[
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
    adapter: AdapterName
    source_url: str
    company_name: str
    sector: str
    industry: str
    scheduled: bool = False


SOURCES: dict[str, SourceDefinition] = {
    "ANZ": SourceDefinition(
        ticker="ANZ",
        adapter="anz",
        source_url=(
            "https://www.anz.com/shareholder/centre/investor-toolkit/"
            "asx-announcements/"
        ),
        company_name="ANZ Group Holdings Limited",
        sector="Financials",
        industry="Banks",
        scheduled=True,
    ),
    "BHP": SourceDefinition(
        ticker="BHP",
        adapter="bhp",
        source_url="https://www.bhp.com/investor-hub/market-announcements",
        company_name="BHP Group Limited",
        sector="Materials",
        industry="Diversified Metals & Mining",
        scheduled=True,
    ),
    "CBA": SourceDefinition(
        ticker="CBA",
        adapter="cba",
        source_url="https://www.commbank.com.au/about-us/investors/asx-announcements.html",
        company_name="Commonwealth Bank of Australia",
        sector="Financials",
        industry="Banks",
        scheduled=True,
    ),
    "COH": SourceDefinition(
        ticker="COH",
        adapter="coh",
        source_url=(
            "https://www.cochlear.com/au/en/corporate/investors/"
            "asx-announcements"
        ),
        company_name="Cochlear Limited",
        sector="Health Care",
        industry="Health Care Equipment & Supplies",
    ),
    "COL": SourceDefinition(
        ticker="COL",
        adapter="col",
        source_url=(
            "https://www.colesgroup.com.au/investors/?page=asx-announcements"
        ),
        company_name="Coles Group Limited",
        sector="Consumer Staples",
        industry="Food & Staples Retailing",
    ),
    "CSL": SourceDefinition(
        ticker="CSL",
        adapter="csl",
        source_url="https://investors.csl.com/investors/asx-announcements",
        company_name="CSL Limited",
        sector="Health Care",
        industry="Biotechnology",
        scheduled=True,
    ),
    "MQG": SourceDefinition(
        ticker="MQG",
        adapter="mqg",
        source_url="https://www.macquarie.com/au/en/investors/reports.html",
        company_name="Macquarie Group Limited",
        sector="Financials",
        industry="Capital Markets",
    ),
    "ORG": SourceDefinition(
        ticker="ORG",
        adapter="org",
        source_url=(
            "https://www.originenergy.com.au/about/investors-media/"
            "media-releases/"
        ),
        company_name="Origin Energy Limited",
        sector="Energy",
        industry="Oil, Gas & Consumable Fuels",
    ),
    "RIO": SourceDefinition(
        ticker="RIO",
        adapter="rio",
        source_url="https://www.riotinto.com/en/invest/exchange-releases",
        company_name="Rio Tinto Limited",
        sector="Materials",
        industry="Diversified Metals & Mining",
    ),
    "TCL": SourceDefinition(
        ticker="TCL",
        adapter="tcl",
        source_url=(
            "https://www.transurban.com/investor-centre/asx-releases.html"
        ),
        company_name="Transurban Group",
        sector="Industrials",
        industry="Highways & Railtracks",
    ),
    "TLS": SourceDefinition(
        ticker="TLS",
        adapter="tls",
        source_url="https://www.telstra.com.au/aboutus/investors/announcements",
        company_name="Telstra Group Limited",
        sector="Communication Services",
        industry="Diversified Telecommunication Services",
    ),
    "WDS": SourceDefinition(
        ticker="WDS",
        adapter="wds",
        source_url="https://www.woodside.com/media-centre/announcements",
        company_name="Woodside Energy Group Limited",
        sector="Energy",
        industry="Oil, Gas & Consumable Fuels",
    ),
    "WES": SourceDefinition(
        ticker="WES",
        adapter="wes",
        source_url=(
            "https://www.wesfarmers.com.au/investor-centre/"
            "company-performance-news/asx-announcements"
        ),
        company_name="Wesfarmers Limited",
        sector="Consumer Discretionary",
        industry="Consumer Staples Distribution & Retail",
        scheduled=True,
    ),
}


def normalise_symbol(value: str) -> str:
    """Return the stored form of an ASX symbol: trimmed, upper-case, no ``.AX``."""
    symbol = value.strip().upper()
    return symbol[:-3] if symbol.endswith(".AX") else symbol


def source_for_ticker(ticker: str) -> SourceDefinition | None:
    return SOURCES.get(normalise_symbol(ticker))


def adapter_matches_ticker(ticker: str, adapter: str) -> bool:
    source = source_for_ticker(ticker)
    return source is not None and source.adapter == adapter


def scheduled_tickers() -> list[str]:
    """Tickers the weekly schedule scrapes when no override is configured."""
    return [ticker for ticker, source in SOURCES.items() if source.scheduled]
