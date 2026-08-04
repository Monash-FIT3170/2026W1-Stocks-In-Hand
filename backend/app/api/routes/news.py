"""API routes for collecting financial news."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.connection import get_db
from app.services import marketaux


router = APIRouter(prefix="/news", tags=["news"])


@router.post("/fetch/{symbol}")
def fetch_symbol_news(
    symbol: str,
    limit: int | None = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Fetch recent Marketaux stories for an ASX ticker and store new rows."""
    fetch_limit = limit if limit is not None else settings.NEWS_FETCH_LIMIT
    try:
        return marketaux.fetch_and_store_news(symbol, fetch_limit, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except marketaux.MarketauxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
