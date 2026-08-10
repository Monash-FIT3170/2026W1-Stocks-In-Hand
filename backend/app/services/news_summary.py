"""Reusable summarisation helpers for stored news artifacts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.artifact_summary import ArtifactSummary
from app.models.ticker import Ticker
from app.services import gemini as summary_service

SUMMARY_METADATA_KEYS = ("summary", "about", "changed", "matters")
NEWS_SOURCE_TYPE = "news"
NEWS_ARTIFACT_TYPE = "news_article"


def summary_text(title: str, summary: dict[str, str]) -> str:
    parts = [summary.get(key) for key in SUMMARY_METADATA_KEYS]
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    return "\n\n".join(cleaned) or title


def has_news_summary_metadata(artifact: Artifact) -> bool:
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    about = metadata.get("about")
    return isinstance(about, str) and bool(about.strip())


def summarise_news_artifact(db: Session, artifact: Artifact) -> ArtifactSummary:
    raw_text = (artifact.raw_text or "").strip()
    if not raw_text:
        raise ValueError("News artifact has no text to summarise")

    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    source_name = metadata.get("source_name")
    source_name = source_name if isinstance(source_name, str) else None
    title = artifact.title or "Untitled news story"

    summary = summary_service.summarise_news_article(
        title=title,
        source_name=source_name,
        raw_text=raw_text,
    )

    next_metadata = dict(metadata)
    for key in SUMMARY_METADATA_KEYS:
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            next_metadata[key] = value
    artifact.artifact_metadata = next_metadata

    db_summary = ArtifactSummary(
        artifact_id=artifact.id,
        summary_text=summary_text(title, summary),
        model_used=summary_service.active_model_name(),
        prompt_version=summary_service.NEWS_SUMMARY_PROMPT_VERSION,
    )
    db.add(db_summary)
    db.commit()
    db.refresh(db_summary)
    return db_summary


def _ticker_for_symbol(db: Session, symbol: str) -> Ticker:
    ticker_symbol = symbol.strip().upper()
    ticker = (
        db.query(Ticker)
        .filter(func.lower(Ticker.symbol) == ticker_symbol.lower())
        .first()
    )
    if not ticker:
        raise ValueError(f"Ticker '{ticker_symbol}' not found")
    return ticker


def _news_artifacts_for_ticker(db: Session, ticker: Ticker, limit: int) -> list[Artifact]:
    return (
        db.query(Artifact)
        .filter(Artifact.ticker_id == ticker.id)
        .filter(Artifact.source_type == NEWS_SOURCE_TYPE)
        .filter(Artifact.artifact_type == NEWS_ARTIFACT_TYPE)
        .filter(Artifact.raw_text.isnot(None))
        .filter((Artifact.is_duplicate.is_(False)) | (Artifact.is_duplicate.is_(None)))
        .order_by(Artifact.published_at.desc().nullslast(), Artifact.created_at.desc())
        .limit(limit)
        .all()
    )


def summarise_news_for_symbol(
    db: Session,
    symbol: str,
    limit: int = 50,
) -> dict[str, Any]:
    ticker = _ticker_for_symbol(db, symbol)
    artifacts = _news_artifacts_for_ticker(db, ticker, limit)
    result: dict[str, Any] = {
        "ticker": ticker.symbol,
        "candidates": len(artifacts),
        "summarised": 0,
        "skipped": 0,
        "errors": [],
    }

    for artifact in artifacts:
        if has_news_summary_metadata(artifact):
            result["skipped"] += 1
            continue

        try:
            summarise_news_artifact(db, artifact)
            result["summarised"] += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result["errors"].append({
                "artifact_id": str(artifact.id),
                "title": artifact.title,
                "message": str(exc),
            })

    return result
