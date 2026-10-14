from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.read_models import ticker_sentiment
from app.read_models.ticker_records import TickerNotFound
from app.read_models.ticker_sentiment import DEFAULT_SENTIMENT_DAYS, DEFAULT_SENTIMENT_LIMIT
from app.schemas.category_sentiment import CategorySentimentResponse

router = APIRouter(prefix="/sentiment", tags=["sentiment"])


@router.get("/{ticker}", response_model=CategorySentimentResponse)
def get_ticker_category_sentiments(
    ticker: str,
    days: int = DEFAULT_SENTIMENT_DAYS,
    limit: int = DEFAULT_SENTIMENT_LIMIT,
    db: Session = Depends(get_db),
):
    """Return stored category sentiment for a ticker."""
    try:
        return ticker_sentiment.read_category_sentiment(db, ticker, days=days, limit=limit)
    except TickerNotFound as exc:
        raise HTTPException(status_code=404, detail="Ticker not found") from exc
