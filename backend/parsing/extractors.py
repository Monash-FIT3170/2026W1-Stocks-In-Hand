"""Internal registry for metric extractors that already exist."""

from __future__ import annotations

from .categories import (
    DividendAnnouncement,
    LeadershipChange,
    ReportCategory,
    SecurityNotification,
)


EXTRACTORS: dict[str, type[ReportCategory]] = {
    "dividend_announcement": DividendAnnouncement,
    "security_notification": SecurityNotification,
    "leadership_change": LeadershipChange,
}


def extractor_for(category: str | None) -> type[ReportCategory] | None:
    """Return an existing metric extractor for a classified category."""
    return EXTRACTORS.get(category) if category else None
