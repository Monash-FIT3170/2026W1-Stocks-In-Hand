from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crud import artifact as artifact_crud
from app.database.connection import get_db
from app.services import gemini as gemini_service

router = APIRouter(prefix="/gemini", tags=["gemini"])


@router.post("/categorise/recent")
def categorise_recent_artifacts(
    ticker: str,
    days: int = 30,
    limit: int = 200,
    offset: int = 0,
    batch_size: int = 0,
    db: Session = Depends(get_db),
):
    chunk = artifact_crud.build_recent_artifact_chunk(
        db=db,
        days=days,
        limit=limit,
        offset=offset,
        ticker_symbol=ticker,
    )

    if not chunk:
        raise HTTPException(
            status_code=404,
            detail="No artifact text found to build chunk",
        )

    try:
        if batch_size > 0:
            categories = gemini_service.categorise_chunk_in_batches(chunk, batch_size)
        else:
            categories = gemini_service.categorise_chunk(chunk)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Gemini request failed") from exc

    return {
        "ticker": ticker.upper(),
        "days": days,
        "model_used": gemini_service.settings.GEMINI_MODEL,
        "batch_size": batch_size,
        "categories": categories,
    }
