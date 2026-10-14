from typing import Literal, Optional

from pydantic import BaseModel


class SourceLink(BaseModel):
    """An artifact's original source, as evidence beside what is said about it."""

    label: str
    title: str
    url: str
    # ISO 8601, or None when the artifact has no date.
    published_at: Optional[str] = None
    # The start of the artifact's raw text. Never shown as a summary.
    evidence_text: Optional[str] = None


class Clarity(BaseModel):
    """Which claims of the latest summary are confirmed facts and which speculation."""

    is_classified: bool
    confirmed_facts: list[str]
    speculation: list[str]


class TickerOverview(BaseModel):
    symbol: str
    company_name: str
    sector: Optional[str]
    sentiment_status: Literal["available", "unavailable"]
    sentiment_label: str
    # The latest record's display date, not the quote's time.
    last_updated: str
    # Formatted strings, "N/A" without a quote.
    current_price: str
    day_change: str
    # None until the latest record has a summary.
    story: Optional[str]
    sources_count: int
    latest_signal_confidence_pct: str
    latest_signal_model: Optional[str]
    # ISO 8601.
    latest_signal_analyzed_at: Optional[str]
    clarity: Clarity
    sources: list[SourceLink]


class KeyNumber(BaseModel):
    label: str
    value: str


class TickerAside(BaseModel):
    key_numbers: list[KeyNumber]
    themes: list[str]


class TickerBrief(BaseModel):
    overview: TickerOverview
    aside: TickerAside
