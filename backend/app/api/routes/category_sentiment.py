import datetime as dt
import re
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.deps import require_admin_investor
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_ticker_mention import ArtifactTickerMention
from app.models.investor import Investor
from app.models.ticker import Ticker
from app.schemas.category_sentiment import (
    CategorySentimentRequest,
    CategorySentimentResponse,
)
from app.services import llm as llm_service

router = APIRouter(prefix="/sentiment", tags=["sentiment"])
CATEGORY_SENTIMENT_KEYS = (*llm_service.CATEGORY_KEYS, "user_discussion")
DEFAULT_SENTIMENT_DAYS = 365
FALLBACK_CATEGORY_KEYWORDS = {
    "revenue": (
        "financial",
        "guidance",
        "revenue",
        "earnings",
        "profit",
        "operational review",
        "quarterly",
        "half year",
    ),
    "strategy": (
        "strategy",
        "strategic",
        "acquisition",
        "growth",
        "project",
        "review",
        "capital allocation",
    ),
    "risk": (
        "risk",
        "impairment",
        "downgrade",
        "decline",
        "conflict",
        "investigation",
        "security",
    ),
    "dividend": ("dividend", "distribution", "buy-back", "buyback", "shareholder return"),
    "organisational": (
        "director",
        "leadership",
        "ceo",
        "chair",
        "appointment",
        "substantial holding",
        "organisational",
    ),
}


def _artifact_summary_text(artifact: Artifact):
    metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    parts = [
        artifact.title,
        metadata.get("about"),
        metadata.get("changed"),
        metadata.get("matters"),
    ]
    if not any(parts):
        parts.append((artifact.raw_text or "")[:600])
    return " ".join(str(part).strip() for part in parts if part).strip()


def _stored_sentiment_rows(
    ticker_id: Any,
    db: Session,
    *,
    days: int,
    limit: int,
) -> list[tuple[Artifact, Any]]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(days, 1))
    return (
        db.query(Artifact, ArtifactSentiment)
        .join(
            ArtifactSentiment,
            ArtifactSentiment.artifact_id == Artifact.id,
        )
        .outerjoin(
            ArtifactTickerMention,
            ArtifactTickerMention.artifact_id == Artifact.id,
        )
        .filter(
            or_(
                Artifact.ticker_id == ticker_id,
                ArtifactTickerMention.ticker_id == ticker_id,
            )
        )
        .filter(
            or_(
                Artifact.published_at >= cutoff,
                and_(
                    Artifact.published_at.is_(None),
                    Artifact.created_at >= cutoff,
                ),
            )
        )
        .order_by(
            Artifact.published_at.desc().nullslast(),
            ArtifactSentiment.created_at.desc(),
        )
        .distinct()
        .limit(max(limit, 1))
        .all()
    )


# Keywords match whole words, with plural and simple verb endings. Stored
# identifiers such as "SecurityNotification" or "security_notification" are
# single words, so "security" no longer files Appendix 3G/3H share notices
# under risk.
_CATEGORY_KEYWORD_PATTERNS = {
    category: re.compile(
        r"(?<![a-z0-9_])(?:"
        + "|".join(re.escape(keyword) for keyword in keywords)
        + r")(?:s|es|d|ed|ing)?(?![a-z0-9_])"
    )
    for category, keywords in FALLBACK_CATEGORY_KEYWORDS.items()
}


def _categories_for_stored_artifact(artifact: Artifact) -> list[str]:
    source_type = str(artifact.source_type or "").lower()
    if source_type in {"reddit", "bluesky", "mastodon", "blog"}:
        return ["user_discussion"]

    metadata = (
        artifact.artifact_metadata
        if isinstance(artifact.artifact_metadata, dict)
        else {}
    )
    haystack = " ".join(
        str(value or "")
        for value in (
            metadata.get("category"),
            artifact.artifact_type,
            artifact.title,
            metadata.get("summary"),
            metadata.get("about"),
            metadata.get("changed"),
            metadata.get("matters"),
        )
    ).lower()
    matches = [
        category
        for category, pattern in _CATEGORY_KEYWORD_PATTERNS.items()
        if pattern.search(haystack)
    ]
    return matches or ["strategy"]


def _unavailable_stored_result(category: str) -> dict[str, Any]:
    label = category.replace("_", " ")
    return {
        "summary": f"No analysed {label} signal is available yet.",
        "available": False,
        "sentiment_label": None,
        "label": None,
        "score": None,
        "confidence_score": None,
        "agreement_score": None,
        "distribution": {},
        "model_used": None,
        "chunks_used": 0,
        "chunks_analyzed": 0,
        "sources_count": 0,
        "sources": [],
        "latest_analyzed_at": None,
    }


def _source_for_stored_artifact(artifact: Artifact) -> dict[str, Any]:
    def text_value(name: str) -> str | None:
        value = getattr(artifact, name, None)
        return value if isinstance(value, str) and value.strip() else None

    published_at = getattr(artifact, "published_at", None)
    if not isinstance(published_at, dt.datetime):
        published_at = None

    return {
        "source_type": text_value("source_type") or "unknown",
        "title": text_value("title"),
        "url": (
            text_value("canonical_url")
            or text_value("document_url")
            or text_value("url")
        ),
        "author": text_value("author"),
        "published_at": published_at,
    }


def _aggregate_stored_category(
    category: str,
    rows: list[tuple[Artifact, Any]],
) -> dict[str, Any]:
    usable: list[tuple[Artifact, Any, str, float]] = []
    for artifact, sentiment in rows:
        label = str(sentiment.sentiment_label or "").lower()
        if label not in {"positive", "neutral", "negative"}:
            continue
        confidence = float(sentiment.confidence_score or 0)
        usable.append((artifact, sentiment, label, min(max(confidence, 0.0), 1.0)))

    if not usable:
        return _unavailable_stored_result(category)

    weights = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    for _artifact, _sentiment, label, confidence in usable:
        weights[label] += confidence
    total_weight = sum(weights.values())
    if total_weight == 0:
        # No row carries any confidence, so count the labels instead.
        for _artifact, _sentiment, label, _confidence in usable:
            weights[label] += 1.0
        total_weight = float(len(usable))
    distribution = {
        label: round(weight / total_weight, 4)
        for label, weight in weights.items()
    }
    dominant = max(distribution, key=lambda label: distribution[label])
    confidence_score = round(
        sum(confidence for _artifact, _sentiment, _label, confidence in usable)
        / len(usable),
        4,
    )
    summaries = []
    for artifact, _sentiment, _label, _confidence in usable:
        summary = _artifact_summary_text(artifact)
        if summary and summary not in summaries:
            summaries.append(summary)
        if len(summaries) == 2:
            break

    models = {
        str(sentiment.model_used)
        for _artifact, sentiment, _label, _confidence in usable
        if sentiment.model_used
    }
    analyzed_dates = [
        sentiment.created_at
        for _artifact, sentiment, _label, _confidence in usable
        if sentiment.created_at
    ]
    latest_analyzed_at = max(analyzed_dates) if analyzed_dates else None
    model_used = next(iter(models)) if len(models) == 1 else "Multiple stored models"
    sources = []
    source_keys = set()
    for artifact, _sentiment, _label, _confidence in usable:
        source = _source_for_stored_artifact(artifact)
        source_key = (source["source_type"], source["url"], source["title"])
        if source_key in source_keys:
            continue
        source_keys.add(source_key)
        sources.append(source)
        if len(sources) == 10:
            break

    return {
        "summary": " ".join(summaries) or f"Based on {len(usable)} analysed signals.",
        "available": True,
        "sentiment_label": dominant,
        "label": dominant,
        "score": distribution[dominant],
        "confidence_score": confidence_score,
        "agreement_score": distribution[dominant],
        "distribution": distribution,
        "model_used": model_used,
        "chunks_used": len(usable),
        "chunks_analyzed": len(usable),
        "sources_count": len(usable),
        "sources": sources,
        "latest_analyzed_at": latest_analyzed_at,
    }


def read_ticker_category_sentiment(
    ticker: str,
    db: Session,
    *,
    days: int = DEFAULT_SENTIMENT_DAYS,
    limit: int = 250,
) -> dict[str, Any]:
    """Read persisted analysis-worker sentiment without invoking FinBERT."""
    ticker_row = (
        db.query(Ticker)
        .filter(Ticker.symbol == ticker.upper())
        .first()
    )
    if not ticker_row:
        raise HTTPException(status_code=404, detail="Ticker not found")

    stored_rows = _stored_sentiment_rows(
        ticker_row.id,
        db,
        days=days,
        limit=limit,
    )
    grouped: dict[str, list[tuple[Artifact, Any]]] = {
        key: [] for key in CATEGORY_SENTIMENT_KEYS
    }
    for artifact, sentiment in stored_rows:
        for category in _categories_for_stored_artifact(artifact):
            grouped[category].append((artifact, sentiment))

    categories = {
        category: _aggregate_stored_category(category, grouped[category])
        for category in CATEGORY_SENTIMENT_KEYS
    }
    available_count = sum(result["available"] for result in categories.values())
    status = (
        "available"
        if available_count == len(CATEGORY_SENTIMENT_KEYS)
        else "partial"
        if available_count
        else "unavailable"
    )
    models = {
        result["model_used"]
        for result in categories.values()
        if result["model_used"]
    }
    analyzed_dates = [
        result["latest_analyzed_at"]
        for result in categories.values()
        if result["latest_analyzed_at"]
    ]
    return {
        "ticker": ticker.upper(),
        "status": status,
        "model_used": (
            next(iter(models))
            if len(models) == 1
            else "Multiple stored models" if models else None
        ),
        "latest_analyzed_at": max(analyzed_dates) if analyzed_dates else None,
        "categories": categories,
    }


def build_ticker_category_sentiment(
    ticker: str,
    body: CategorySentimentRequest | None,
    db: Session,
    days: int = DEFAULT_SENTIMENT_DAYS,
    asx_limit: int = 200,
    reddit_limit: int = 50,
    bluesky_limit: int = 50,
    mastodon_limit: int = 50,
    offset: int = 0,
    batch_size: int = 0,
    persist: bool = True,
):
    """Preserve the legacy POST contract without API-runtime inference."""
    request_body = body or CategorySentimentRequest()
    if request_body.categories or request_body.reddit_summary:
        raise HTTPException(
            status_code=503,
            detail=(
                "On-demand FinBERT inference is not available in the API runtime. "
                "Submit documents through the analysis pipeline, then read stored sentiment."
            ),
        )

    _ = (offset, batch_size, persist)
    return read_ticker_category_sentiment(
        ticker=ticker,
        db=db,
        days=days,
        limit=asx_limit + reddit_limit,
    )


@router.get("/{ticker}", response_model=CategorySentimentResponse)
def get_ticker_category_sentiments(
    ticker: str,
    days: int = DEFAULT_SENTIMENT_DAYS,
    limit: int = 250,
    db: Session = Depends(get_db),
):
    """Return stored category sentiment for a ticker."""
    return read_ticker_category_sentiment(
        ticker=ticker,
        db=db,
        days=days,
        limit=limit,
    )


@router.post("/{ticker}", response_model=CategorySentimentResponse)
def analyse_ticker_category_sentiments(
    ticker: str,
    body: CategorySentimentRequest | None = Body(default=None),
    days: int = DEFAULT_SENTIMENT_DAYS,
    asx_limit: int = 200,
    reddit_limit: int = 50,
    bluesky_limit: int = 50,
    mastodon_limit: int = 50,
    offset: int = 0,
    batch_size: int = 0,
    persist: bool = True,
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    """Compatibility endpoint for clients that previously posted this request."""
    return build_ticker_category_sentiment(
        ticker=ticker,
        body=body,
        days=days,
        asx_limit=asx_limit,
        reddit_limit=reddit_limit,
        bluesky_limit=bluesky_limit,
        mastodon_limit=mastodon_limit,
        offset=offset,
        batch_size=batch_size,
        persist=persist,
        db=db,
    )
