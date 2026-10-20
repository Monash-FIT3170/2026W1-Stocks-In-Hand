from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.crud import ticker as crud
from app.content_topic_vocabulary import CONTENT_TOPICS
from app.database.connection import get_db
from app.read_models import ticker_brief, ticker_records, ticker_topics
from app.read_models.ticker_records import TickerNotFound
from app.schemas.ticker import TickerCreate, TickerResponse, TickerUpdate
from app.schemas.ticker_brief import TickerBrief
from app.schemas.ticker_records import DeepDiveEvent, NewsFeedRecord
from app.schemas.ticker_topics import TickerTopics
from app.services.quotes import QuoteSource, live_quotes

router = APIRouter(prefix="/tickers", tags=["tickers"])


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


@router.get("/symbol/{symbol}/news-feed", response_model=list[NewsFeedRecord])
def get_ticker_news_feed(symbol: str, db: Session = Depends(get_db)):
    """A ticker's newest records, each as its artifact card."""
    try:
        return ticker_records.read_news_feed(db, symbol)
    except TickerNotFound as exc:
        raise HTTPException(status_code=404, detail="Ticker not found") from exc


@router.get("/symbol/{symbol}/deep-dive-timeline", response_model=list[DeepDiveEvent])
def get_ticker_deep_dive_timeline(symbol: str, db: Session = Depends(get_db), topic: str | None = None):
    """A ticker's research history from its stored records; with none it is empty."""
    topic = (topic or "").strip() or None
    if topic is not None and topic not in CONTENT_TOPICS:
        raise HTTPException(status_code=422, detail="Unknown content topic")
    try:
        return ticker_records.read_deep_dive(db, symbol, topic=topic)
    except TickerNotFound as exc:
        raise HTTPException(status_code=404, detail="Ticker not found") from exc


@router.get("/symbol/{symbol}/topics", response_model=TickerTopics)
def get_ticker_topics(
    symbol: str,
    days: int = Query(
        default=ticker_topics.DEFAULT_WINDOW_DAYS,
        ge=1,
        le=ticker_topics.MAX_WINDOW_DAYS,
    ),
    db: Session = Depends(get_db),
):
    """A ticker's content topics, their trends, and the topic clusters seen in ``days``."""
    try:
        return ticker_topics.read_ticker_topics(db, symbol, window_days=days)
    except TickerNotFound as exc:
        raise HTTPException(status_code=404, detail="Ticker not found") from exc
