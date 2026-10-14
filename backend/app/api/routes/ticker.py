from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crud import ticker as crud
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.read_models import ticker_sentiment
from app.schemas.ticker import TickerCreate, TickerResponse, TickerUpdate
from app.services import artifact_card, artifact_summary
from app.services.quotes import Quote, QuoteSource, live_quotes

router = APIRouter(prefix="/tickers", tags=["tickers"])


def _money(value) -> str:
    if value is None:
        return "N/A"
    return f"${float(value):,.2f}"


def _day_change(quote: Quote | None) -> str:
    change = quote.day_change() if quote else None
    return "N/A" if change is None else f"{change:+.2f}%"


def _sentiment_label(value: str | None) -> str:
    labels = {
        "positive": "Generally Positive",
        "negative": "Generally Negative",
        "neutral": "Neutral",
    }
    return labels.get((value or "").lower(), "Unavailable")


def _clean_text(value):
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _metadata_value(artifact: Artifact, key: str, fallback: str) -> str:
    metadata = artifact.artifact_metadata or {}
    return _clean_text(metadata.get(key)) or fallback


def _format_announcement_time(artifact: Artifact) -> str:
    if artifact.published_at:
        return f"{artifact.published_at.strftime('%b')} {artifact.published_at.day}, {artifact.published_at.year}"
    return "Recently"


def _format_month(value):
    if not value:
        return "Recent"
    return value.strftime("%b %Y")


def _format_key_date(value):
    if not value:
        return "No filings yet"
    return value.strftime("%b %Y")


def _ticker_artifacts(db: Session, ticker_id: UUID, limit: int = 10) -> list[Artifact]:
    return (
        db.query(Artifact)
        .options(artifact_summary.WITH_SUMMARY)
        .filter(Artifact.ticker_id == ticker_id)
        .order_by(Artifact.published_at.desc().nullslast(), Artifact.created_at.desc())
        .limit(limit)
        .all()
    )


def _themes_from_artifacts(artifacts: list[Artifact], limit: int = 5) -> list[str]:
    themes: list[str] = []
    seen: set[str] = set()

    for artifact in artifacts:
        metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
        label = artifact_card.label(metadata.get("category"), artifact.artifact_type)
        if label.lower() == "unknown":
            label = artifact_card.label(artifact.artifact_type, "Announcement")
        theme = f"{label} activity"
        key = theme.lower()
        if key not in seen:
            themes.append(theme)
            seen.add(key)
        if len(themes) >= limit:
            break

    return themes


def _ticker_brief_payload(symbol: str, db: Session, quotes: QuoteSource) -> dict:
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    quote = quotes.quote(ticker.symbol)
    artifacts = _ticker_artifacts(db, ticker.id, limit=20)
    latest_artifact = artifacts[0] if artifacts else None
    signal = ticker_sentiment.latest_signals(db, [ticker.id]).get(ticker.id)
    latest_summary = artifact_summary.read(latest_artifact) if latest_artifact else None
    sources = artifact_card.sources(latest_artifact) if latest_artifact else []
    confidence_pct = (
        f"{round(signal.confidence_score * 100)}%"
        if signal and signal.confidence_score is not None
        else "N/A"
    )

    overview = {
        "symbol": ticker.symbol,
        "company_name": ticker.company_name,
        "sector": ticker.sector or ticker.industry or ticker.exchange,
        "sentiment_status": "available" if signal else "unavailable",
        "sentiment_label": _sentiment_label(signal.sentiment_label if signal else None),
        "last_updated": (
            _format_announcement_time(latest_artifact)
            if latest_artifact
            else "No updates yet"
        ),
        "current_price": _money(quote.price if quote else None),
        "day_change": _day_change(quote),
        "story": artifact_summary.brief(latest_summary),
        "sources_count": len(sources),
        "latest_signal_confidence_pct": confidence_pct,
        "latest_signal_model": signal.model_used if signal else None,
        "latest_signal_analyzed_at": (
            signal.analyzed_at.isoformat() if signal and signal.analyzed_at else None
        ),
        # Deprecated compatibility field. New consumers must use the accurately
        # named latest-signal field above.
        "public_sentiment_pct": confidence_pct,
        "clarity": artifact_summary.clarity(latest_summary),
        "sources": sources,
    }
    aside = {
        "key_numbers": [
            {"label": "Current price", "value": _money(quote.price if quote else None)},
            {"label": "Day change", "value": _day_change(quote)},
            {
                "label": "Latest filing",
                "value": _format_key_date(
                    latest_artifact.published_at if latest_artifact else None
                ),
            },
            {
                "label": "Latest type",
                "value": (
                    artifact_card.label(
                        _metadata_value(
                            latest_artifact,
                            "category",
                            latest_artifact.artifact_type,
                        ),
                        latest_artifact.artifact_type,
                    )
                    if latest_artifact
                    else "No filings yet"
                ),
            },
        ],
        "themes": _themes_from_artifacts(artifacts),
    }
    return {"overview": overview, "aside": aside}


@router.post("/", response_model=TickerResponse)
def create_ticker(
    ticker: TickerCreate,
    db: Session = Depends(get_db),
):
    existing = crud.get_ticker_by_symbol(db, symbol=ticker.symbol)
    if existing:
        raise HTTPException(status_code=400, detail="Ticker symbol already exists")
    return crud.create_ticker(db=db, ticker=ticker)


@router.get("/", response_model=list[TickerResponse])
def get_tickers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_tickers(db, skip=skip, limit=limit)


@router.get("/symbol/{symbol}", response_model=TickerResponse)
def get_ticker_by_symbol(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker


@router.get("/{ticker_id}", response_model=TickerResponse)
def get_ticker(ticker_id: UUID, db: Session = Depends(get_db)):
    ticker = crud.get_ticker(db, ticker_id=ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker


@router.patch("/{ticker_id}", response_model=TickerResponse)
def update_ticker(
    ticker_id: UUID,
    data: TickerUpdate,
    db: Session = Depends(get_db),
):
    ticker = crud.get_ticker(db, ticker_id=ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return crud.update_ticker(
        db=db,
        ticker_id=ticker_id,
        data=data.model_dump(exclude_unset=True),
    )


@router.get("/symbol/{symbol}/brief")
def get_ticker_brief(
    symbol: str,
    db: Session = Depends(get_db),
    quotes: QuoteSource = Depends(live_quotes),
):
    """Return the overview and aside from one quote and artifact lookup."""
    return _ticker_brief_payload(symbol, db, quotes)


@router.get("/symbol/{symbol}/news-feed")
def get_ticker_news_feed(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    artifacts = _ticker_artifacts(db, ticker.id)
    return [
        {
            "id": str(artifact.id),
            "ticker": ticker.symbol,
            "time": _format_announcement_time(artifact),
            **artifact_card.artifact_card(artifact).fields(),
            "sources": artifact_card.sources(artifact),
        }
        for artifact in artifacts
    ]


@router.get("/symbol/{symbol}/deep-dive-timeline")
def get_ticker_deep_dive_timeline(symbol: str, db: Session = Depends(get_db)):
    """Return only persisted filing events; an empty history stays empty."""
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    artifacts = _ticker_artifacts(db, ticker.id)
    timeline = []
    for artifact in artifacts:
        summary = artifact_summary.read(artifact)
        timeline.append(
            {
                "month": _format_month(artifact.published_at),
                "tag": artifact_card.label(
                    _metadata_value(artifact, "category", artifact.artifact_type),
                    artifact.artifact_type,
                ),
                "title": artifact.title or f"{ticker.symbol} update",
                "date": _format_announcement_time(artifact),
                "detail": summary.text if summary else None,
                "metrics": [f"Source: {artifact.source_type or artifact.artifact_type}"],
                "tone": "green",
                "sources": artifact_card.sources(artifact),
            }
        )

    return timeline
