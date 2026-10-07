from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import SessionLocal, get_db
from app.services import discussion_collector
from app.services.discussion_sources.base import InvalidTargetError
from app.services.discussion_sources.bluesky import BLUESKY, SEARCH_PATH

router = APIRouter(prefix="/bluesky", tags=["bluesky"])

BLUESKY_SEARCH_PATH = SEARCH_PATH


def _get_or_create_bluesky_platform(db: Session):
    """For the scheduled collector until it calls the collector directly."""
    return discussion_collector.platform_for(db, BLUESKY, "")


def _run_bluesky_scrape(query: str, limit: int, scrape_run_id: UUID | None = None) -> None:
    """For the scheduled collector until it calls the collector directly."""
    discussion_collector.collect(
        BLUESKY, query, limit, session_scope=SessionLocal, run_id=scrape_run_id
    )


@router.post("/scrape")
def scrape_and_store(
    background_tasks: BackgroundTasks,
    query: str = "ASX",
    limit: int = 25,
    db: Session = Depends(get_db),
):
    try:
        target = BLUESKY.target(query, limit)
    except InvalidTargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run, _created = discussion_collector.request_collection(
        db,
        BLUESKY,
        target,
        idempotency_key=f"public-discussion:bluesky:{uuid4()}",
    )
    background_tasks.add_task(
        discussion_collector.collect,
        BLUESKY,
        target,
        limit,
        session_scope=SessionLocal,
        run_id=run.id,
    )
    return {
        "status": "queued",
        "query": target,
        "limit": limit,
        "scrape_run_id": run.id,
    }
