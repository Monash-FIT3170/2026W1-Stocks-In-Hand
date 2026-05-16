from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.crud import announcement as crud
from app.database.connection import get_db
from app.schemas.announcement import AnnouncementResponse


router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("/", response_model=list[AnnouncementResponse])
def list_announcements(
    limit: int = 50,
    offset: int = 0,
    today: bool = False,
    sector: str | None = None,
    db: Session = Depends(get_db),
):
    return crud.get_announcements(db, limit=limit, offset=offset, today=today, sector=sector)
