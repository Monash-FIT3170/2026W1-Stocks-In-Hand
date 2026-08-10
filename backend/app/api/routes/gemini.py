from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from uuid import UUID

from app.crud import artifact as artifact_crud
from app.crud import artifact_summary as artifact_summary_crud
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.services import gemini as gemini_service

router = APIRouter(prefix="/gemini", tags=["gemini"])


def _summary_text(title: str, summary: dict[str, object]) -> str:
    parts = [
        summary.get("summary"),
        summary.get("about"),
        summary.get("changed"),
        summary.get("matters"),
    ]
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    return "\n\n".join(cleaned) or title


def _generate_artifact_summary(
    artifact: Artifact,
    metadata: dict,
) -> tuple[dict[str, object], str]:
    if artifact.source_type == "news" or artifact.artifact_type == "news_article":
        return (
            gemini_service.summarise_news_article(
                title=artifact.title or "Untitled news story",
                source_name=metadata.get("source_name"),
                raw_text=artifact.raw_text,
            ),
            gemini_service.NEWS_SUMMARY_PROMPT_VERSION,
        )

    category = str(metadata.get("category") or artifact.artifact_type or "UNKNOWN")
    extracted_data = (
        metadata.get("extracted_data")
        if isinstance(metadata.get("extracted_data"), dict)
        else {}
    )
    return (
        gemini_service.summarise_announcement(
            title=artifact.title or "Untitled ASX announcement",
            category=category,
            extracted_data=extracted_data,
            raw_text=artifact.raw_text,
        ),
        gemini_service.SUMMARY_PROMPT_VERSION,
    )


def _summary_metadata(metadata: dict, summary: dict[str, object]) -> dict:
    """Merge generated summary fields into JSON metadata without mutating input."""
    next_metadata = dict(metadata)

    for key in gemini_service.SUMMARY_TEXT_KEYS:
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            next_metadata[key] = value.strip()

    for key in gemini_service.SUMMARY_LIST_KEYS:
        if key in summary:
            value = summary.get(key)
            next_metadata[key] = list(value) if isinstance(value, list) else []

    return next_metadata


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
        "model_used": gemini_service.active_model_name(),
        "batch_size": batch_size,
        "categories": categories,
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
        if metadata.get("about"):
            skipped += 1
            continue

        try:
            summary, prompt_version = _generate_artifact_summary(artifact, metadata)
        except Exception as exc:
            errors.append({"artifact_id": str(artifact.id), "error": str(exc)})
            continue

        artifact.artifact_metadata = _summary_metadata(metadata, summary)

        artifact_summary_crud.upsert_artifact_summary(
            db,
            artifact_id=artifact.id,
            summary_text=_summary_text(artifact.title or "Untitled artifact", summary),
            model_used=gemini_service.active_model_name(),
            prompt_version=prompt_version,
        )
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
        summary, prompt_version = _generate_artifact_summary(artifact, metadata)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Groq summary request failed") from exc

    artifact.artifact_metadata = _summary_metadata(metadata, summary)

    db_summary = artifact_summary_crud.upsert_artifact_summary(
        db,
        artifact_id=artifact.id,
        summary_text=_summary_text(
            artifact.title or "Untitled artifact",
            summary,
        ),
        model_used=gemini_service.active_model_name(),
        prompt_version=prompt_version,
    )

    return {
        "artifact_id": artifact.id,
        "summary_id": db_summary.id,
        "model_used": db_summary.model_used,
        "prompt_version": db_summary.prompt_version,
        **summary,
    }
