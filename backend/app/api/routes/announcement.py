from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.content_topic_vocabulary import CONTENT_TOPICS
from app.crud import announcement as crud
from app.database.connection import get_db
from app.schemas.announcement import AnnouncementResponse, TrendingAnnouncementResponse


router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("/trending", response_model=list[TrendingAnnouncementResponse])
def list_trending_announcements(
    days: int = 7,
    limit: int = 4,
    db: Session = Depends(get_db),
):
    return crud.get_trending_announcements(db, days=days, limit=limit)


@router.get("", response_model=list[AnnouncementResponse], include_in_schema=False)
@router.get("/", response_model=list[AnnouncementResponse])
def list_announcements(
    limit: int = 50,
    offset: int = 0,
    today: bool = False,
    sector: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    topic: str | None = None,
    db: Session = Depends(get_db),
):
    topic = (topic or "").strip() or None
    if topic is not None and topic not in CONTENT_TOPICS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown topic. Use one of: {', '.join(CONTENT_TOPICS)}",
        )
    return crud.get_announcements(
        db,
        limit=limit,
        offset=offset,
        today=today,
        sector=sector,
        start_date=start_date,
        end_date=end_date,
        topic=topic,
    )
