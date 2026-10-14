import time
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crud import ticker as crud
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.schemas.ticker import TickerCreate, TickerResponse, TickerUpdate
from app.services import artifact_card, artifact_summary

router = APIRouter(prefix="/tickers", tags=["tickers"])

QUOTE_CACHE_TTL_SECONDS = 300
QUOTE_FAILURE_TTL_SECONDS = 60
# symbol -> (fetched_at, quote or None). Quotes are read live from Yahoo instead of being
# stored, so there is no market data table behind the price cards. Failures are cached too,
# for a shorter window, so a symbol Yahoo cannot resolve does not cost an HTTP timeout on
# every page load.
_QUOTE_CACHE: dict[str, tuple[float, tuple[float, float] | None]] = {}


def _fetch_quote(symbol: str) -> tuple[float, float] | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.AX"
    try:
        timeout = httpx.Timeout(2.5, connect=1.5)
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        result = response.json().get("chart", {}).get("result") or []
        if not result:
            return None

        meta = result[0].get("meta", {})
        current_price = meta.get("regularMarketPrice")
        previous_close = meta.get("chartPreviousClose") or meta.get(
            "regularMarketPreviousClose"
        )
        if current_price is None or previous_close is None:
            return None
        return float(current_price), float(previous_close)
    except Exception:
        return None


def _live_quote(symbol: str) -> tuple[float, float] | None:
    """Current price and previous close for a ticker, cached briefly in-process.

    Returns None when Yahoo is unreachable or the response cannot be parsed, so
    callers degrade to "N/A" rather than failing the request.
    """
    now = time.monotonic()
    cached = _QUOTE_CACHE.get(symbol)
    if cached:
        fetched_at, cached_quote = cached
        ttl = QUOTE_CACHE_TTL_SECONDS if cached_quote else QUOTE_FAILURE_TTL_SECONDS
        if now - fetched_at < ttl:
            return cached_quote

    quote = _fetch_quote(symbol)
    _QUOTE_CACHE[symbol] = (now, quote)
    return quote


def _money(value) -> str:
    if value is None:
        return "N/A"
    return f"${float(value):,.2f}"


def _day_change(quote: tuple[float, float] | None) -> str:
    if not quote:
        return "N/A"
    current, previous = quote
    if previous == 0:
        return "N/A"
    change = ((current - previous) / previous) * 100
    return f"{change:+.2f}%"


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


def _latest_sentiment_for_ticker(db: Session, ticker_id: UUID) -> ArtifactSentiment | None:
    return (
        db.query(ArtifactSentiment)
        .join(Artifact, ArtifactSentiment.artifact_id == Artifact.id)
        .filter(Artifact.ticker_id == ticker_id)
        .order_by(ArtifactSentiment.created_at.desc())
        .first()
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


def _ticker_brief_payload(symbol: str, db: Session) -> dict:
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    quote = _live_quote(ticker.symbol)
    artifacts = _ticker_artifacts(db, ticker.id, limit=20)
    latest_artifact = artifacts[0] if artifacts else None
    latest_sentiment = _latest_sentiment_for_ticker(db, ticker.id)
    latest_summary = artifact_summary.read(latest_artifact) if latest_artifact else None
    sources = artifact_card.sources(latest_artifact) if latest_artifact else []
    confidence_pct = (
        f"{round(float(latest_sentiment.confidence_score) * 100)}%"
        if latest_sentiment and latest_sentiment.confidence_score is not None
        else "N/A"
    )

    overview = {
        "symbol": ticker.symbol,
        "company_name": ticker.company_name,
        "sector": ticker.sector or ticker.industry or ticker.exchange,
        "sentiment_status": "available" if latest_sentiment else "unavailable",
        "sentiment_label": _sentiment_label(
            latest_sentiment.sentiment_label if latest_sentiment else None
        ),
        "last_updated": (
            _format_announcement_time(latest_artifact)
            if latest_artifact
            else "No updates yet"
        ),
        "current_price": _money(quote[0] if quote else None),
        "day_change": _day_change(quote),
        "story": artifact_summary.brief(latest_summary),
        "sources_count": len(sources),
        "latest_signal_confidence_pct": confidence_pct,
        "latest_signal_model": latest_sentiment.model_used if latest_sentiment else None,
        "latest_signal_analyzed_at": (
            latest_sentiment.created_at.isoformat()
            if latest_sentiment and latest_sentiment.created_at
            else None
        ),
        # Deprecated compatibility field. New consumers must use the accurately
        # named latest-signal field above.
        "public_sentiment_pct": confidence_pct,
        "clarity": artifact_summary.clarity(latest_summary),
        "sources": sources,
    }
    aside = {
        "key_numbers": [
            {"label": "Current price", "value": _money(quote[0] if quote else None)},
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
def get_ticker_brief(symbol: str, db: Session = Depends(get_db)):
    """Return the overview and aside from one quote and artifact lookup."""
    return _ticker_brief_payload(symbol, db)


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
