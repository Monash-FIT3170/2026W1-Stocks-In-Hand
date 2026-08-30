"""Internal registry for metric extractors that already exist."""

from __future__ import annotations

from .categories import (
    CorporateAction,
    DividendAnnouncement,
    ExecutiveTranscript,
    HalfYearResults,
    LeadershipChange,
    QuarterlyTradingUpdate,
    ReportCategory,
    SecurityNotification,
)


EXTRACTORS: dict[str, type[ReportCategory]] = {
    "quarterly_trading_update": QuarterlyTradingUpdate,
    "half_year_results": HalfYearResults,
    "dividend_announcement": DividendAnnouncement,
    "security_notification": SecurityNotification,
    "corporate_action": CorporateAction,
    "leadership_change": LeadershipChange,
    "executive_transcript": ExecutiveTranscript,
}


def extractor_for(category: str | None) -> type[ReportCategory] | None:
    """Return an existing metric extractor for a classified category."""
    return EXTRACTORS.get(category) if category else None
