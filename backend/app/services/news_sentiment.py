"""Sentiment helpers for stored news artifacts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.services import news_summary
from app.services import sentiment as sentiment_service


def has_news_sentiment(db: Session, artifact: Artifact) -> bool:
    return (
        db.query(ArtifactSentiment)
        .filter(ArtifactSentiment.artifact_id == artifact.id)
        .first()
        is not None
    )


def analyse_news_artifact_sentiment(db: Session, artifact: Artifact) -> ArtifactSentiment:
    raw_text = (artifact.raw_text or "").strip()
    if not raw_text:
        raise ValueError("News artifact has no text to analyse")

    result = sentiment_service.analyse_text(raw_text)
    db_sentiment = ArtifactSentiment(
        artifact_id=artifact.id,
        sentiment_label=result["sentiment_label"],
        stance=result["label"],
        confidence_score=result["confidence_score"],
        model_used=result["model_used"],
    )
    db.add(db_sentiment)
    db.commit()
    db.refresh(db_sentiment)
    return db_sentiment


def analyse_news_sentiment_for_symbol(
    db: Session,
    symbol: str,
    limit: int = 50,
) -> dict[str, Any]:
    ticker = news_summary._ticker_for_symbol(db, symbol)
    artifacts = news_summary._news_artifacts_for_ticker(db, ticker, limit)
    result: dict[str, Any] = {
        "ticker": ticker.symbol,
        "candidates": len(artifacts),
        "analysed": 0,
        "skipped": 0,
        "errors": [],
    }

    for artifact in artifacts:
        if has_news_sentiment(db, artifact):
            result["skipped"] += 1
            continue

        try:
            analyse_news_artifact_sentiment(db, artifact)
            result["analysed"] += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result["errors"].append({
                "artifact_id": str(artifact.id),
                "title": artifact.title,
                "message": str(exc),
            })

    return result
