from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin_investor
from app.database.connection import get_db
from app.models.investor import Investor
from app.schemas.public_discussion import (
    PublicDiscussionRequeueResponse,
    PublicDiscussionStatusResponse,
)
from app.services import public_discussion as public_discussion_service

router = APIRouter(prefix="/public-discussion", tags=["public-discussion"])


@router.get(
    "/ticker/{ticker_symbol}/status",
    response_model=PublicDiscussionStatusResponse,
)
def get_ticker_status(
    ticker_symbol: str,
    db: Session = Depends(get_db),
):
    try:
        return public_discussion_service.public_discussion_status(db, ticker_symbol)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/analysis/requeue",
    response_model=PublicDiscussionRequeueResponse,
)
def requeue_analysis(
    execute: bool = False,
    ticker: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    try:
        return public_discussion_service.requeue_pending_analysis(
            db,
            ticker_symbol=ticker,
            limit=limit,
            execute=execute,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail:
            status_code = status.HTTP_404_NOT_FOUND
        elif "not configured" in detail:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
