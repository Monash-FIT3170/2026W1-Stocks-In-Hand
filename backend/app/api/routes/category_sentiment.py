from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crud import artifact as artifact_crud
from app.api.routes import reddit as reddit_route
from app.database.connection import get_db
from app.schemas.category_sentiment import CategorySentimentRequest
from app.schemas.category_sentiment import CategorySentimentResponse
from app.services import gemini as gemini_service
from app.services import sentiment as sentiment_service

router = APIRouter(prefix="/sentiment", tags=["sentiment"])


def _build_category_map(body: CategorySentimentRequest):
    category_map: dict[str, str | None] = dict(body.categories)
    if body.reddit_summary:
        category_map["user_discussion"] = body.reddit_summary.summary
    return category_map


def _run_finbert(ticker: str, category_map: dict[str, str | None],):
    try:
        categories = sentiment_service.analyse_categories(category_map)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="FinBERT sentiment analysis failed") from exc

    return {
        "ticker": ticker.upper(),
        "model_used": sentiment_service.model_name(),
        "categories": categories,
    }


def _categorise_recent_asx(ticker: str, db: Session, days: int, asx_limit: int, offset: int, batch_size: int,):
    chunk = artifact_crud.build_recent_artifact_chunk(
        db=db,
        days=days,
        limit=asx_limit,
        offset=offset,
        ticker_symbol=ticker,
    )

    if not chunk:
        return {}

    try:
        if batch_size > 0:
            return gemini_service.categorise_chunk_in_batches(
                chunk,
                batch_size,
            )
        return gemini_service.categorise_chunk(chunk)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Gemini categorisation request failed",
        ) from exc


def _summarise_recent_reddit(ticker: str, db: Session, days: int, reddit_limit: int,):
    posts = artifact_crud.get_reddit_posts_for_ticker(
        db=db,
        ticker_symbol=ticker.upper(),
        days=days,
        limit=reddit_limit,
    )

    if not posts:
        return {
            "summary": f"No Reddit posts mentioning {ticker.upper()} in the last {days} days.",
            "dominant_sentiment": "neutral",
            "key_themes": [],
        }

    post_dicts = [
        {
            "title": artifact.title or "",
            "body": artifact.raw_text or "",
            "score": (artifact.artifact_metadata or {}).get("score", 0),
            "url": artifact.url or "",
        }
        for artifact in posts
    ]

    try:
        return reddit_route._summarise_reddit_posts(
            ticker_symbol=ticker.upper(),
            posts=post_dicts,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Reddit Groq summarisation request failed",
        ) from exc


@router.post("/{ticker}", response_model=CategorySentimentResponse)
def analyse_ticker_category_sentiments(
    ticker: str,
    body: CategorySentimentRequest | None = Body(default=None),
    days: int = 30,
    asx_limit: int = 200,
    reddit_limit: int = 50,
    offset: int = 0,
    batch_size: int = 0,
    db: Session = Depends(get_db),
):
    request_body = body or CategorySentimentRequest()
    category_map = _build_category_map(request_body)

    if not request_body.categories:
        category_map.update(
            _categorise_recent_asx(
                ticker=ticker,
                db=db,
                days=days,
                asx_limit=asx_limit,
                offset=offset,
                batch_size=batch_size,
            )
        )

    if not request_body.reddit_summary:
        reddit_summary = _summarise_recent_reddit(
            ticker=ticker,
            db=db,
            days=days,
            reddit_limit=reddit_limit,
        )
        category_map["user_discussion"] = str(reddit_summary.get("summary", ""))

    if not category_map:
        raise HTTPException(
            status_code=404,
            detail="No ASX categories or Reddit summary text found",
        )
    if not any(text for text in category_map.values()):
        raise HTTPException(status_code=404, detail="All sentiment input text is empty")

    return _run_finbert(ticker=ticker, category_map=category_map)
