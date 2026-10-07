from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_investor
from app.crud import artifact as artifact_crud
from app.database.connection import SessionLocal, get_db
from app.models.investor import Investor
from app.services import discussion_collector
from app.services import llm as llm_service
from app.services.discussion_sources.base import InvalidTargetError
from app.services.discussion_sources.reddit import REDDIT

router = APIRouter(prefix="/reddit", tags=["reddit"])

def _summarise_reddit_posts(ticker_symbol: str, posts: list[dict], source_name: str = "Reddit") -> dict:
    if not posts:
        return {
            "summary": f"No relevant {source_name} posts found.",
            "post_count": 0,
        }

    result = llm_service.summarise_reddit_digest(
        ticker_symbol=ticker_symbol,
        posts=posts,
        source_name=source_name,
    )
    return {**result, "post_count": len(posts)}


def _get_or_create_reddit_platform(db: Session):
    """For the scheduled collector until it calls the collector directly."""
    return discussion_collector.platform_for(db, REDDIT, "")


def _run_reddit_scrape(subreddit: str, limit: int, scrape_run_id: UUID | None = None) -> None:
    """For the scheduled collector until it calls the collector directly."""
    discussion_collector.collect(
        REDDIT, subreddit, limit, session_scope=SessionLocal, run_id=scrape_run_id
    )


@router.post("/scrape")
def scrape_and_store(
    background_tasks: BackgroundTasks,
    subreddit: str = "ASX",
    limit: int = 10,
    db: Session = Depends(get_db),
):
    if not REDDIT.configured():
        raise HTTPException(
            status_code=500,
            detail="REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be configured",
        )
    try:
        target = REDDIT.target(subreddit, limit)
    except InvalidTargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run, _created = discussion_collector.request_collection(
        db,
        REDDIT,
        target,
        idempotency_key=f"public-discussion:reddit:{uuid4()}",
    )
    background_tasks.add_task(
        discussion_collector.collect,
        REDDIT,
        target,
        limit,
        session_scope=SessionLocal,
        run_id=run.id,
    )
    return {
        "status": "queued",
        "subreddit": target,
        "limit": limit,
        "scrape_run_id": run.id,
    }

@router.get("/ticker-sentiment/{ticker_symbol}")
def reddit_ticker_sentiment(
    ticker_symbol: str,
    days: int = 30,
    limit: int = 50,
    db: Session = Depends(get_db),
    _investor: Investor = Depends(get_current_investor),
):
    posts = artifact_crud.get_reddit_posts_for_ticker(
        db=db,
        ticker_symbol=ticker_symbol.upper(),
        days=days,
        limit=limit,
    )

    if not posts:
        return {
            "ticker":             ticker_symbol.upper(),
            "post_count":         0,
            "summary":            "No Reddit posts mentioning this ticker in the last 30 days.",
            "dominant_sentiment": None,
            "key_themes":         [],
            "posts_used":         [],
        }

    post_dicts = [
        {
            "title": a.title or "",
            "body":  a.raw_text or "",
            "score": (a.artifact_metadata or {}).get("score", 0),
            "url":   a.url or "",
        }
        for a in posts
    ]

    try:
        result = _summarise_reddit_posts(
            ticker_symbol=ticker_symbol.upper(),
            posts=post_dicts,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ticker":        ticker_symbol.upper(),
        "days_searched": days,
        **result,
        "posts_used": [
            {
                "title": a.title,
                "url":   a.url,
                "score": (a.artifact_metadata or {}).get("score", 0),
            }
            for a in posts
        ],
    }
