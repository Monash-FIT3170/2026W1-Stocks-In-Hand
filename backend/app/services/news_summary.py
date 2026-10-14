"""Reusable summarisation helpers for stored news artifacts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.ticker import Ticker
from app.services import artifact_summary, generation
from app.services.artifact_summary import RecordedSummary
from app.services.llm_errors import LLMUnavailableError

NEWS_SOURCE_TYPE = "news"
NEWS_ARTIFACT_TYPE = "news_article"


def summarise_news_artifact(db: Session, artifact: Artifact) -> RecordedSummary:
    """Summarise one stored news story, record the summary and commit."""
    raw_text = (artifact.raw_text or "").strip()
    if not raw_text:
        raise ValueError("News artifact has no text to summarise")

    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    source_name = metadata.get("source_name")
    source_name = source_name if isinstance(source_name, str) else None
    title = artifact.title or "Untitled news story"

    generated = generation.generate(
        generation.NewsSummary(title=title, source_name=source_name, raw_text=raw_text)
    )
    if isinstance(generated, generation.Unavailable):
        raise LLMUnavailableError(generated.reason)

    recorded = artifact_summary.record(db, artifact, artifact_summary.from_generated(generated))
    db.commit()
    return recorded


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
        .options(artifact_summary.WITH_SUMMARY)
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
    # Decide the work before the first commit, which expires every loaded
    # artifact and its summary rows, so a later check would query again.
    pending = [artifact for artifact in artifacts if artifact_summary.needs_summary(artifact)]
    result: dict[str, Any] = {
        "ticker": ticker.symbol,
        "candidates": len(artifacts),
        "summarised": 0,
        "skipped": len(artifacts) - len(pending),
        "errors": [],
    }

    for artifact in pending:
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
