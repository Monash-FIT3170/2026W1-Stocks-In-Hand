from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crud import ticker as crud
from app.database.connection import get_db
from app.read_models import ticker_brief
from app.read_models.ticker_records import TickerNotFound, recent_artifacts, record_date
from app.schemas.ticker import TickerCreate, TickerResponse, TickerUpdate
from app.schemas.ticker_brief import TickerBrief
from app.services import artifact_card, artifact_summary
from app.services.quotes import QuoteSource, live_quotes

router = APIRouter(prefix="/tickers", tags=["tickers"])


def _format_month(value):
    if not value:
        return "Recent"
    return value.strftime("%b %Y")


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


@router.get("/symbol/{symbol}/brief", response_model=TickerBrief)
def get_ticker_brief(
    symbol: str,
    db: Session = Depends(get_db),
    quotes: QuoteSource = Depends(live_quotes),
):
    """The overview and aside a ticker's research summary opens with."""
    try:
        return ticker_brief.read_ticker_brief(db, symbol, quotes=quotes)
    except TickerNotFound as exc:
        raise HTTPException(status_code=404, detail="Ticker not found") from exc


@router.get("/symbol/{symbol}/news-feed")
def get_ticker_news_feed(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    artifacts = recent_artifacts(db, ticker.id, limit=10)
    return [
        {
            "id": str(artifact.id),
            "ticker": ticker.symbol,
            "time": record_date(artifact),
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

    artifacts = recent_artifacts(db, ticker.id, limit=10)
    timeline = []
    for artifact in artifacts:
        summary = artifact_summary.read(artifact)
        timeline.append(
            {
                "month": _format_month(artifact.published_at),
                "tag": artifact_card.tag(artifact),
                "title": artifact.title or f"{ticker.symbol} update",
                "date": record_date(artifact),
                "detail": summary.text if summary else None,
                "metrics": [f"Source: {artifact.source_type or artifact.artifact_type}"],
                "tone": "green",
                "sources": artifact_card.sources(artifact),
            }
        )

    return timeline
