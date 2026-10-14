from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crud import artifact as artifact_crud
from app.database.connection import get_db
from app.services import analysis_queue, generation
from app.services.analysis_queue import AnalysisQueueUnavailable, AnalysisSender

router = APIRouter(prefix="/llm", tags=["llm"])
T = TypeVar("T")


def _available(
    result: generation.Generated[T] | generation.Unavailable,
) -> generation.Generated[T]:
    """The generated result, or 503 when no LLM is switched on."""
    if isinstance(result, generation.Unavailable):
        raise HTTPException(status_code=503, detail=result.reason)
    return result


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
        result = generation.generate(generation.CategorySplit(chunk, batch_size=batch_size))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="LLM categorisation request failed") from exc
    result = _available(result)

    return {
        "ticker": ticker.upper(),
        "days": days,
        "model_used": result.model,
        "batch_size": batch_size,
        "categories": result.value,
    }


@router.post("/summarise/ticker/{symbol}", status_code=202)
def summarise_ticker_artifacts(
    symbol: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    send: AnalysisSender = Depends(analysis_queue.analysis_sender),
):
    """Queue a new summary of each of a ticker's artifacts without a complete one."""
    try:
        return analysis_queue.request_ticker_summaries(db, symbol, limit=limit, send=send)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnalysisQueueUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/summarise/artifact/{artifact_id}", status_code=202)
def summarise_artifact(
    artifact_id: UUID,
    db: Session = Depends(get_db),
    send: AnalysisSender = Depends(analysis_queue.analysis_sender),
):
    """Queue a new summary of one artifact, which replaces its summary."""
    try:
        return analysis_queue.request_summary(db, artifact_id, send=send)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnalysisQueueUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
