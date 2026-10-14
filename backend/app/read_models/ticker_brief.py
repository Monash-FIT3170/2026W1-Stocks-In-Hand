"""Ticker brief: what a ticker's research summary opens with.

The overview names the company, its live quote and its latest signal, and
tells the story of its latest record with that record's sources and
clarity. The aside gives the latest filing's date and type and the kinds of
record the ticker has had lately.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.read_models.ticker_records import find_ticker, recent_artifacts, record_date
from app.read_models.ticker_sentiment import LatestSignal, latest_signals
from app.schemas.ticker_brief import KeyNumber, TickerAside, TickerBrief, TickerOverview
from app.services import artifact_card, artifact_summary
from app.services.quotes import Quote, QuoteSource

# The themes come from this many of the newest records, and at most
# MAX_THEMES of them are shown.
THEME_RECORDS = 20
MAX_THEMES = 5
_SENTIMENT_LABELS = {
    "positive": "Generally Positive",
    "negative": "Generally Negative",
    "neutral": "Neutral",
}


def read_ticker_brief(db: Session, symbol: str, *, quotes: QuoteSource) -> TickerBrief:
    """The brief of the ticker stored under ``symbol``.

    Asks the quote source once, for the stored symbol. Raises
    ``TickerNotFound`` for a symbol with no ticker.
    """
    ticker = find_ticker(db, symbol)
    quote = quotes.quote(ticker.symbol)
    artifacts = recent_artifacts(db, ticker.id, limit=THEME_RECORDS)
    latest = artifacts[0] if artifacts else None
    signal = latest_signals(db, [ticker.id]).get(ticker.id)
    summary = artifact_summary.read(latest) if latest else None
    sources = artifact_card.sources(latest) if latest else []

    overview = TickerOverview(
        symbol=ticker.symbol,
        company_name=ticker.company_name,
        sector=ticker.sector or ticker.industry or ticker.exchange,
        sentiment_status="available" if signal else "unavailable",
        sentiment_label=_sentiment_label(signal),
        last_updated=record_date(latest) if latest else "No updates yet",
        current_price=f"${quote.price:,.2f}" if quote else "N/A",
        day_change=_day_change(quote),
        story=artifact_summary.brief(summary),
        sources_count=len(sources),
        latest_signal_confidence_pct=(
            f"{round(signal.confidence_score * 100)}%"
            if signal and signal.confidence_score is not None
            else "N/A"
        ),
        latest_signal_model=signal.model_used if signal else None,
        latest_signal_analyzed_at=(
            signal.analyzed_at.isoformat() if signal and signal.analyzed_at else None
        ),
        clarity=artifact_summary.clarity(summary),
        sources=sources,
    )
    aside = TickerAside(
        key_numbers=[
            KeyNumber(
                label="Latest filing",
                value=(
                    latest.published_at.strftime("%b %Y")
                    if latest and latest.published_at
                    else "No filings yet"
                ),
            ),
            KeyNumber(
                label="Latest type",
                value=artifact_card.tag(latest) if latest else "No filings yet",
            ),
        ],
        themes=_themes(artifacts),
    )
    return TickerBrief(overview=overview, aside=aside)


def _sentiment_label(signal: LatestSignal | None) -> str:
    label = signal.sentiment_label if signal else ""
    return _SENTIMENT_LABELS.get(label.lower(), "Unavailable")


def _day_change(quote: Quote | None) -> str:
    change = quote.day_change() if quote else None
    return "N/A" if change is None else f"{change:+.2f}%"


def _themes(artifacts: list[Artifact]) -> list[str]:
    """The kinds of record the ticker has had lately, newest first, each once."""
    themes: list[str] = []
    seen: set[str] = set()
    for artifact in artifacts:
        label = artifact_card.tag(artifact)
        if label.lower() == "unknown":
            label = artifact_card.label(artifact.artifact_type, "Announcement")
        theme = f"{label} activity"
        if theme.lower() not in seen:
            themes.append(theme)
            seen.add(theme.lower())
        if len(themes) >= MAX_THEMES:
            break
    return themes
