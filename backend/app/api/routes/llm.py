from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.crud import artifact as artifact_crud
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.services import artifact_summary, generation

router = APIRouter(prefix="/llm", tags=["llm"])
T = TypeVar("T")


def _generate_artifact_summary(
    artifact: Artifact,
    metadata: dict,
) -> generation.Generated[dict[str, object]] | generation.Unavailable:
    """Summarise a news story or an announcement with its own prompt."""
    if artifact.source_type == "news" or artifact.artifact_type == "news_article":
        kind = generation.NewsSummary(
            title=artifact.title or "Untitled news story",
            source_name=metadata.get("source_name"),
            raw_text=artifact.raw_text,
        )
    else:
        kind = generation.AnnouncementSummary(
            title=artifact.title or "Untitled ASX announcement",
            category=str(metadata.get("category") or artifact.artifact_type or "UNKNOWN"),
            extracted_data=(
                metadata.get("extracted_data")
                if isinstance(metadata.get("extracted_data"), dict)
                else {}
            ),
            raw_text=artifact.raw_text,
        )
    return generation.generate(kind)


def _available(
    result: generation.Generated[T] | generation.Unavailable,
) -> generation.Generated[T]:
    """The generated result, or 503 when no LLM is switched on."""
    if isinstance(result, generation.Unavailable):
        raise HTTPException(status_code=503, detail=result.reason)
    return result


def _has_current_summary(metadata: dict) -> bool:
    """Return whether metadata includes both summary copy and clarity lists."""
    return bool(metadata.get("about")) and all(
        isinstance(metadata.get(key), list)
        for key in generation.SUMMARY_LIST_KEYS
    )


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


@router.post("/summarise/ticker/{symbol}")
def summarise_ticker_artifacts(
    symbol: str,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    ticker = (
        db.query(Ticker)
        .filter(func.lower(Ticker.symbol) == symbol.lower())
        .first()
    )
    if not ticker:
        raise HTTPException(status_code=404, detail=f"Ticker '{symbol}' not found")

    artifacts = (
        db.query(Artifact)
        .filter(Artifact.ticker_id == ticker.id)
        .filter(Artifact.source_type.in_(["asx_announcement", "news"]))
        .filter(Artifact.raw_text.isnot(None))
        .order_by(Artifact.published_at.desc())
        .limit(limit)
        .all()
    )

    processed = 0
    skipped = 0
    errors = []

    for artifact in artifacts:
        metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
        if _has_current_summary(metadata):
            skipped += 1
            continue

        try:
            generated = _generate_artifact_summary(artifact, metadata)
        except Exception as exc:
            errors.append({"artifact_id": str(artifact.id), "error": str(exc)})
            continue
        summary = artifact_summary.from_generated(_available(generated))

        try:
            artifact_summary.record(db, artifact, summary)
        except artifact_summary.EmptySummary as exc:
            errors.append({"artifact_id": str(artifact.id), "error": str(exc)})
            continue
        # Commit each artifact, which releases its row lock before the next.
        db.commit()
        processed += 1

    return {
        "ticker": symbol.upper(),
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
    }


@router.post("/summarise/artifact/{artifact_id}")
def summarise_artifact(
    artifact_id: UUID,
    db: Session = Depends(get_db),
):
    artifact = artifact_crud.get_artifact(db, artifact_id=artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not artifact.raw_text:
        raise HTTPException(status_code=404, detail="Artifact has no text to summarise")

    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    try:
        generated = _generate_artifact_summary(artifact, metadata)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="LLM summary request failed") from exc
    generated = _available(generated)

    try:
        recorded = artifact_summary.record(
            db,
            artifact,
            artifact_summary.from_generated(generated),
        )
    except artifact_summary.EmptySummary as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.commit()

    return {
        "artifact_id": artifact.id,
        "summary_id": recorded.summary_id,
        "model_used": recorded.summary.model,
        "prompt_version": recorded.summary.prompt_version,
        **generated.value,
    }
