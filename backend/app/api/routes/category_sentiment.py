import datetime as dt
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.crud import artifact as artifact_crud
from app.crud import artifact_sentiment as artifact_sentiment_crud
from app.api.routes import reddit as reddit_route
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.ticker import Ticker
from app.schemas.category_sentiment import CategorySentimentRequest
from app.schemas.category_sentiment import CategorySentimentResponse
from app.services import groq as groq_service
from app.services import sentiment as sentiment_service

router = APIRouter(prefix="/sentiment", tags=["sentiment"])
CATEGORY_SENTIMENT_KEYS = (*groq_service.CATEGORY_KEYS, "user_discussion")
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


def _empty_category_map():
    return {key: "" for key in CATEGORY_SENTIMENT_KEYS}


def _build_category_map(body: CategorySentimentRequest):
    category_map: dict[str, str | None] = _empty_category_map()
    category_map.update(body.categories)
    if body.reddit_summary:
        category_map["user_discussion"] = body.reddit_summary.summary
    return category_map


def _run_finbert(ticker: str, category_map: dict[str, str | None],):
    try:
        categories = sentiment_service.analyse_categories(category_map)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="FinBERT sentiment analysis failed") from exc

    return {
        "ticker": ticker.upper(),
        "model_used": sentiment_service.model_name(),
        "categories": categories,
    }


def _recent_asx_artifacts(ticker: str, db: Session, days: int, limit: int, offset: int):
    ticker_row = (
        db.query(Ticker)
        .filter(Ticker.symbol == ticker.upper())
        .first()
    )
    if not ticker_row:
        return []

    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        db.query(Artifact)
        .filter(Artifact.ticker_id == ticker_row.id)
        .filter(Artifact.source_type == "asx_announcement")
        .filter(Artifact.published_at >= cutoff)
        .order_by(Artifact.published_at.desc().nullslast(), Artifact.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


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


def _fallback_recent_asx_categories(
    ticker: str,
    db: Session,
    days: int,
    asx_limit: int,
    offset: int,
):
    categories = {key: "" for key in groq_service.CATEGORY_KEYS}
    artifacts = _recent_asx_artifacts(
        ticker=ticker,
        db=db,
        days=days,
        limit=asx_limit,
        offset=offset,
    )

    for artifact in artifacts:
        text = _artifact_summary_text(artifact)
        if not text:
            continue

        haystack = " ".join(
            str(value or "")
            for value in (
                artifact.artifact_type,
                artifact.title,
                (artifact.artifact_metadata or {}).get("category")
                if isinstance(artifact.artifact_metadata, dict)
                else "",
                text,
            )
        ).lower()
        matched = [
            category
            for category, keywords in FALLBACK_CATEGORY_KEYWORDS.items()
            if any(keyword in haystack for keyword in keywords)
        ]
        if not matched:
            matched = ["strategy"]

        for category in matched:
            categories[category] = "\n\n".join(
                part for part in (categories[category], text) if part
            )

    return categories


def _aggregate_category_sentiment(categories: dict[str, dict]):
    totals = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    total_weight = 0.0

    for result in categories.values():
        distribution = result.get("distribution") or {}
        weight = max(float(result.get("chunks_used") or 1), 1.0)
        for label in totals:
            totals[label] += float(distribution.get(label) or 0.0) * weight
        total_weight += weight

    if total_weight <= 0:
        return None

    distribution = {
        label: round(score / total_weight, 4)
        for label, score in totals.items()
    }
    sentiment_label = max(distribution, key=lambda label: distribution[label])
    return {
        "sentiment_label": sentiment_label,
        "confidence_score": distribution[sentiment_label],
    }


def _persist_latest_ticker_sentiment(db: Session, ticker: str, categories: dict[str, dict]) -> None:
    aggregate = _aggregate_category_sentiment(categories)
    if not aggregate:
        return

    ticker_row = (
        db.query(Ticker)
        .filter(Ticker.symbol == ticker.upper())
        .first()
    )
    if not ticker_row:
        return

    artifact = (
        db.query(Artifact)
        .filter(Artifact.ticker_id == ticker_row.id)
        .order_by(Artifact.published_at.desc().nullslast(), Artifact.created_at.desc())
        .first()
    )
    if not artifact:
        return

    artifact_sentiment_crud.upsert_artifact_sentiment(
        db,
        artifact_id=artifact.id,
        sentiment_label=aggregate["sentiment_label"],
        stance="ticker_pipeline",
        confidence_score=aggregate["confidence_score"],
        model_used=sentiment_service.model_name(),
    )


def _categorise_recent_asx(ticker: str, db: Session, days: int, asx_limit: int, offset: int, batch_size: int,):
    chunk = artifact_crud.build_recent_artifact_chunk(
        db=db,
        days=days,
        limit=asx_limit,
        offset=offset,
        ticker_symbol=ticker,
    )

    fallback_categories = _fallback_recent_asx_categories(
        ticker=ticker,
        db=db,
        days=days,
        asx_limit=asx_limit,
        offset=offset,
    )

    if not chunk:
        return fallback_categories

    try:
        if batch_size > 0:
            categories = groq_service.categorise_chunk_in_batches(
                chunk,
                batch_size,
            )
        else:
            categories = groq_service.categorise_chunk(chunk)
        if any(categories.values()):
            return categories
        return fallback_categories
    except RuntimeError as exc:
        print(f"[SENTIMENT] ASX categorisation fallback for {ticker}: {exc}")
        return fallback_categories
    except ValueError as exc:
        print(f"[SENTIMENT] ASX categorisation fallback for {ticker}: {exc}")
        return fallback_categories
    except Exception as exc:
        print(f"[SENTIMENT] ASX categorisation fallback for {ticker}: {exc}")
        return fallback_categories


def _summarise_recent_public_discussion(
    ticker: str,
    db: Session,
    days: int,
    reddit_limit: int,
    bluesky_limit: int,
    mastodon_limit: int,
):
    reddit_posts = artifact_crud.get_reddit_posts_for_ticker(
        db=db,
        ticker_symbol=ticker.upper(),
        days=days,
        limit=reddit_limit,
    )
    bluesky_posts = artifact_crud.get_bluesky_posts_for_ticker(
        db=db,
        ticker_symbol=ticker.upper(),
        days=days,
        limit=bluesky_limit,
    )
    mastodon_posts = artifact_crud.get_mastodon_posts_for_ticker(
        db=db,
        ticker_symbol=ticker.upper(),
        days=days,
        limit=mastodon_limit,
    )

    if not reddit_posts and not bluesky_posts and not mastodon_posts:
        return {
            "summary": f"No public discussion posts mentioning {ticker.upper()} in the last {days} days.",
            "dominant_sentiment": "neutral",
            "key_themes": [],
        }

    post_dicts = [
        {
            "title": artifact.title or "",
            "body": artifact.raw_text or "",
            "score": (artifact.artifact_metadata or {}).get("score", 0),
            "url": artifact.url or "",
        }
        for artifact in reddit_posts
    ]
    post_dicts.extend(
        {
            "title": artifact.title or "",
            "body": artifact.raw_text or "",
            "score": sum(
                int((artifact.artifact_metadata or {}).get(key, 0) or 0)
                for key in ("like_count", "repost_count", "reply_count", "quote_count")
            ),
            "url": artifact.url or "",
        }
        for artifact in bluesky_posts
    )
    post_dicts.extend(
        {
            "title": artifact.title or "",
            "body": artifact.raw_text or "",
            "score": sum(
                int((artifact.artifact_metadata or {}).get(key, 0) or 0)
                for key in ("favourites_count", "reblogs_count", "replies_count")
            ),
            "url": artifact.url or "",
        }
        for artifact in mastodon_posts
    )

    try:
        return reddit_route._summarise_reddit_posts(
            ticker_symbol=ticker.upper(),
            posts=post_dicts,
            source_name="Reddit, Bluesky and Mastodon",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Public discussion Groq summarisation request failed",
        ) from exc


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
        .filter(Artifact.ticker_id == ticker_id)
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
        .limit(max(limit, 1))
        .all()
    )


def _categories_for_stored_artifact(artifact: Artifact) -> list[str]:
    source_type = str(artifact.source_type or "").lower()
    if source_type in {"reddit", "bluesky", "mastodon"}:
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
        for category, keywords in FALLBACK_CATEGORY_KEYWORDS.items()
        if any(keyword in haystack for keyword in keywords)
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
        "latest_analyzed_at": None,
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
        weights[label] += confidence or 1.0
    total_weight = sum(weights.values())
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
