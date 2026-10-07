from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import SessionLocal, get_db
from app.services import discussion_collector
from app.services.discussion_sources.base import InvalidTargetError
from app.services.discussion_sources.mastodon import MASTODON

router = APIRouter(prefix="/mastodon", tags=["mastodon"])


@router.post("/scrape")
def scrape_and_store(
    background_tasks: BackgroundTasks,
    tag: str = "ASX",
    limit: int = 25,
    db: Session = Depends(get_db),
):
    try:
        target = MASTODON.target(tag, limit)
    except InvalidTargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    run, _created = discussion_collector.request_collection(
        db,
        MASTODON,
        target,
        idempotency_key=f"public-discussion:mastodon:{uuid4()}",
    )
    background_tasks.add_task(
        discussion_collector.collect,
        MASTODON,
        target,
        limit,
        session_scope=SessionLocal,
        run_id=run.id,
    )
    return {
        "status": "queued",
        "tag": target,
        "limit": limit,
        "scrape_run_id": run.id,
    }
