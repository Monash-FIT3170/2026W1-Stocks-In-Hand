from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.read_models import ticker_sentiment
from app.read_models.ticker_records import TickerNotFound
from app.read_models.ticker_sentiment import DEFAULT_SENTIMENT_DAYS, DEFAULT_SENTIMENT_LIMIT
from app.schemas.category_sentiment import (
    CategorySentimentRequest,
    CategorySentimentResponse,
)

router = APIRouter(prefix="/sentiment", tags=["sentiment"])


def _category_sentiment(
    db: Session,
    ticker: str,
    *,
    days: int,
    limit: int,
) -> CategorySentimentResponse:
    try:
        return ticker_sentiment.read_category_sentiment(db, ticker, days=days, limit=limit)
    except TickerNotFound as exc:
        raise HTTPException(status_code=404, detail="Ticker not found") from exc


def build_ticker_category_sentiment(
    ticker: str,
    body: CategorySentimentRequest | None,
    db: Session,
    days: int = DEFAULT_SENTIMENT_DAYS,
    asx_limit: int = 200,
    reddit_limit: int = 50,
    bluesky_limit: int = 50,
    mastodon_limit: int = 50,
    offset: int = 0,
    batch_size: int = 0,
    persist: bool = True,
):
    """Preserve the legacy POST contract without API-runtime inference."""
    request_body = body or CategorySentimentRequest()
    if request_body.categories or request_body.reddit_summary:
        raise HTTPException(
            status_code=503,
            detail=(
                "On-demand FinBERT inference is not available in the API runtime. "
                "Submit documents through the analysis pipeline, then read stored sentiment."
            ),
        )

    _ = (offset, batch_size, persist)
    return _category_sentiment(db, ticker, days=days, limit=asx_limit + reddit_limit)


@router.get("/{ticker}", response_model=CategorySentimentResponse)
def get_ticker_category_sentiments(
    ticker: str,
    days: int = DEFAULT_SENTIMENT_DAYS,
    limit: int = DEFAULT_SENTIMENT_LIMIT,
    db: Session = Depends(get_db),
):
    """Return stored category sentiment for a ticker."""
    return _category_sentiment(db, ticker, days=days, limit=limit)


@router.post("/{ticker}", response_model=CategorySentimentResponse)
def analyse_ticker_category_sentiments(
    ticker: str,
    body: CategorySentimentRequest | None = Body(default=None),
    days: int = DEFAULT_SENTIMENT_DAYS,
    asx_limit: int = 200,
    reddit_limit: int = 50,
    bluesky_limit: int = 50,
    mastodon_limit: int = 50,
    offset: int = 0,
    batch_size: int = 0,
    persist: bool = True,
    db: Session = Depends(get_db),
):
    """Compatibility endpoint for clients that previously posted this request."""
    return build_ticker_category_sentiment(
        ticker=ticker,
        body=body,
        days=days,
        asx_limit=asx_limit,
        reddit_limit=reddit_limit,
        bluesky_limit=bluesky_limit,
        mastodon_limit=mastodon_limit,
        offset=offset,
        batch_size=batch_size,
        persist=persist,
        db=db,
    )
