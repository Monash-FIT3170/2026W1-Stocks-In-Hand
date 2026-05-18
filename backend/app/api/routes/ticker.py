from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.models.market_data import MarketData
from app.schemas.ticker import TickerCreate, TickerResponse
from app.crud import ticker as crud

router = APIRouter(prefix="/tickers", tags=["tickers"])


def _money(value) -> str:
    if value is None:
        return "N/A"
    return f"${float(value):,.2f}"


def _latest_market_rows(db: Session, ticker_id: UUID) -> list[MarketData]:
    return (
        db.query(MarketData)
        .filter(MarketData.ticker_id == ticker_id)
        .order_by(MarketData.price_date.desc())
        .limit(2)
        .all()
    )


def _day_change(rows: list[MarketData]) -> str:
    if len(rows) < 2 or rows[0].close_price is None or rows[1].close_price is None:
        return "N/A"
    previous = float(rows[1].close_price)
    if previous == 0:
        return "N/A"
    change = ((float(rows[0].close_price) - previous) / previous) * 100
    return f"{change:+.2f}%"


def _sentiment_label(value: str | None) -> str:
    labels = {
        "positive": "Generally Positive",
        "negative": "Generally Negative",
        "neutral": "Neutral",
    }
    return labels.get((value or "").lower(), "Neutral")


def _metadata_value(artifact: Artifact, key: str, fallback: str) -> str:
    metadata = artifact.artifact_metadata or {}
    return metadata.get(key) or fallback


def _format_announcement_time(artifact: Artifact) -> str:
    if artifact.published_at:
        return artifact.published_at.strftime("%b %-d, %Y")
    return "Recently"


def _ticker_artifacts(db: Session, ticker_id: UUID, limit: int = 10) -> list[Artifact]:
    return (
        db.query(Artifact)
        .filter(Artifact.ticker_id == ticker_id)
        .order_by(Artifact.published_at.desc().nullslast(), Artifact.created_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/", response_model=TickerResponse)
def create_ticker(ticker: TickerCreate, db: Session = Depends(get_db)):
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
def update_ticker(ticker_id: UUID, data: dict, db: Session = Depends(get_db)):
    ticker = crud.get_ticker(db, ticker_id=ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return crud.update_ticker(db=db, ticker_id=ticker_id, data=data)

@router.get("/symbol/{symbol}/overview")
def get_ticker_overview(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    market_rows = _latest_market_rows(db, ticker.id)
    latest_price = market_rows[0].close_price if market_rows else None
    artifacts = _ticker_artifacts(db, ticker.id, limit=20)
    latest_artifact = artifacts[0] if artifacts else None
    latest_sentiment = None
    if latest_artifact:
        latest_sentiment = (
            db.query(ArtifactSentiment)
            .filter(ArtifactSentiment.artifact_id == latest_artifact.id)
            .order_by(ArtifactSentiment.created_at.desc())
            .first()
        )

    story = (
        _metadata_value(latest_artifact, "about", latest_artifact.raw_text[:240])
        if latest_artifact and latest_artifact.raw_text
        else (
            f"{ticker.symbol} is tracked from the StonksInHand database. "
            "Add announcements and analysis data to enrich this brief."
        )
    )

    return {
        "symbol": ticker.symbol,
        "company_name": ticker.company_name,
        "sector": ticker.sector or ticker.industry or ticker.exchange,
        "sentiment_label": _sentiment_label(
            latest_sentiment.sentiment_label if latest_sentiment else None
        ),
        "last_updated": (
            _format_announcement_time(latest_artifact)
            if latest_artifact
            else "No updates yet"
        ),
        "current_price": _money(latest_price),
        "day_change": _day_change(market_rows),
        "story": story,
        "sources_count": len(artifacts),
        "public_sentiment_pct": (
            f"{round(float(latest_sentiment.confidence_score or 0) * 100)}%"
            if latest_sentiment
            else "N/A"
        )
    }

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
            "tag": _metadata_value(
                artifact,
                "category",
                artifact.source_type or artifact.artifact_type,
            ),
            "time": _format_announcement_time(artifact),
            "title": artifact.title or f"{ticker.symbol} announcement",
            "about": _metadata_value(
                artifact,
                "about",
                artifact.raw_text[:160] if artifact.raw_text else "No summary available yet.",
            ),
            "changed": _metadata_value(artifact, "changed", "No change summary available yet."),
            "matters": _metadata_value(artifact, "matters", "No investment impact summary available yet."),
            "url": artifact.url,
        }
        for artifact in artifacts
    ]

@router.get("/symbol/{symbol}/deep-dive-timeline")
def get_ticker_deep_dive_timeline(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    artifacts = _ticker_artifacts(db, ticker.id)
    timeline = []
    for artifact in artifacts:
        summary = (
            db.query(ArtifactSummary)
            .filter(ArtifactSummary.artifact_id == artifact.id)
            .order_by(ArtifactSummary.created_at.desc())
            .first()
        )
        timeline.append(
            {
                "month": (
                    artifact.published_at.strftime("%b %Y")
                    if artifact.published_at
                    else "Recent"
                ),
                "tag": _metadata_value(artifact, "category", artifact.artifact_type),
                "title": artifact.title or f"{ticker.symbol} update",
                "date": _format_announcement_time(artifact),
                "detail": (
                    summary.summary_text
                    if summary
                    else (
                        artifact.raw_text[:240]
                        if artifact.raw_text
                        else "No detail available yet."
                    )
                ),
                "metrics": [f"Source: {artifact.source_type or artifact.artifact_type}"],
                "tone": "green" if artifact.credibility_label == "official" else "orange",
            }
        )

    if timeline:
        return timeline

    return [
        {
            "month": "Recent",
            "tag": "Database",
            "title": f"{ticker.symbol} profile created",
            "date": "No announcements yet",
            "detail": (
                f"{ticker.company_name} exists in the database, "
                "but no announcement timeline has been loaded yet."
            ),
            "metrics": [ticker.exchange],
            "tone": "green"
        }
    ]
