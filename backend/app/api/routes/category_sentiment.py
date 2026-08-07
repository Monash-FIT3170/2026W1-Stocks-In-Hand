from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crud import artifact as artifact_crud
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

    db.add(ArtifactSentiment(
        artifact_id=artifact.id,
        sentiment_label=aggregate["sentiment_label"],
        stance="ticker_pipeline",
        confidence_score=aggregate["confidence_score"],
        model_used=sentiment_service.model_name(),
    ))
    db.commit()


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


def _summarise_recent_reddit(ticker: str, db: Session, days: int, reddit_limit: int,):
    posts = artifact_crud.get_reddit_posts_for_ticker(
        db=db,
        ticker_symbol=ticker.upper(),
        days=days,
        limit=reddit_limit,
    )

    if not posts:
        return {
            "summary": f"No Reddit posts mentioning {ticker.upper()} in the last {days} days.",
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
        for artifact in posts
    ]

    try:
        return reddit_route._summarise_reddit_posts(
            ticker_symbol=ticker.upper(),
            posts=post_dicts,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Reddit Groq summarisation request failed",
        ) from exc


def build_ticker_category_sentiment(
    ticker: str,
    body: CategorySentimentRequest | None,
    db: Session,
    days: int = DEFAULT_SENTIMENT_DAYS,
    asx_limit: int = 200,
    reddit_limit: int = 50,
    offset: int = 0,
    batch_size: int = 0,
    persist: bool = True,
):
    request_body = body or CategorySentimentRequest()
    category_map = _build_category_map(request_body)

    if not request_body.categories:
        category_map.update(
            _categorise_recent_asx(
                ticker=ticker,
                db=db,
                days=days,
                asx_limit=asx_limit,
                offset=offset,
                batch_size=batch_size,
            )
        )

    if not request_body.reddit_summary:
        reddit_summary = _summarise_recent_reddit(
            ticker=ticker,
            db=db,
            days=days,
            reddit_limit=reddit_limit,
        )
        category_map["user_discussion"] = str(reddit_summary.get("summary", ""))

    if not category_map:
        raise HTTPException(
            status_code=404,
            detail="No ASX categories or Reddit summary text found",
        )
    if not any(text for text in category_map.values()):
        raise HTTPException(status_code=404, detail="All sentiment input text is empty")

    result = _run_finbert(ticker=ticker, category_map=category_map)
    if persist:
        _persist_latest_ticker_sentiment(
            db=db,
            ticker=ticker,
            categories=result["categories"],
        )
    return result


@router.post("/{ticker}", response_model=CategorySentimentResponse)
def analyse_ticker_category_sentiments(
    ticker: str,
    body: CategorySentimentRequest | None = Body(default=None),
    days: int = DEFAULT_SENTIMENT_DAYS,
    asx_limit: int = 200,
    reddit_limit: int = 50,
    offset: int = 0,
    batch_size: int = 0,
    persist: bool = True,
    db: Session = Depends(get_db),
):
    return build_ticker_category_sentiment(
        ticker=ticker,
        body=body,
        days=days,
        asx_limit=asx_limit,
        reddit_limit=reddit_limit,
        offset=offset,
        batch_size=batch_size,
        persist=persist,
        db=db,
    )
