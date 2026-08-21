"""Marketaux news collection, normalisation, and artifact storage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud import artifact as artifact_crud
from app.crud import information_platform as platform_crud
from app.crud import ticker as ticker_crud
from app.schemas.artifact import ArtifactCreate, ArtifactType, SourceType
from app.schemas.information_platform import InformationPlatformCreate
from app.schemas.ticker import TickerCreate
from app.services import news_summary
from app.services.title_normalization import normalise_title


PROVIDER_NAME = "Marketaux"
PROVIDER_KEY = "marketaux"


class MarketauxError(RuntimeError):
    """Raised when Marketaux cannot provide a usable response."""


@dataclass(frozen=True)
class NewsArticle:
    """Provider-independent representation of one collected news article."""

    provider_id: str | None
    title: str
    url: str
    published_at: datetime | None
    source_name: str | None
    author: str | None
    raw_text: str
    text_used: str
    snippet: str | None = None
    description: str | None = None
    symbols: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    image_url: str | None = None


def normalise_asx_symbol(symbol: str) -> str:
    """Return the database form of an ASX symbol, for example ``BHP``."""
    cleaned = symbol.strip().upper()
    if cleaned.endswith(".AX"):
        cleaned = cleaned[:-3]
    if not cleaned:
        raise ValueError("Ticker symbol must not be empty")
    return cleaned


def marketaux_asx_symbol(symbol: str) -> str:
    """Return Marketaux's exchange-qualified ASX symbol."""
    return f"{normalise_asx_symbol(symbol)}.AX"


def select_article_text(payload: dict[str, Any]) -> tuple[str, str]:
    """Choose the best available article text and report its source field."""
    for key in ("full_text", "description", "snippet", "title"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), key
    raise ValueError("Marketaux article has no usable text")


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid Marketaux published_at value: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _source_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("name", "domain"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _author(payload: dict[str, Any]) -> str | None:
    author = payload.get("author")
    if isinstance(author, str) and author.strip():
        return author.strip()
    authors = payload.get("authors")
    if isinstance(authors, list):
        cleaned = [str(value).strip() for value in authors if str(value).strip()]
        return ", ".join(cleaned) or None
    return None


def normalise_article(payload: dict[str, Any]) -> NewsArticle:
    """Map a Marketaux response item into the internal article shape."""
    url = str(payload.get("url") or "").strip()
    raw_title = str(payload.get("title") or "").strip()
    if not raw_title:
        raise ValueError("Marketaux article is missing a title")
    if not url:
        raise ValueError("Marketaux article is missing a URL")
    title = normalise_title(raw_title, url)

    raw_entities = payload.get("entities")
    entities = (
        [entity for entity in raw_entities if isinstance(entity, dict)]
        if isinstance(raw_entities, list)
        else []
    )
    symbols = sorted({
        str(entity.get("symbol")).strip().upper()
        for entity in entities
        if isinstance(entity, dict) and entity.get("symbol")
    })
    raw_text, text_used = select_article_text(payload)

    return NewsArticle(
        provider_id=str(payload.get("uuid") or "").strip() or None,
        title=title,
        url=url,
        published_at=_parse_datetime(payload.get("published_at")),
        source_name=_source_name(payload.get("source")),
        author=_author(payload),
        raw_text=raw_text,
        text_used=text_used,
        snippet=(str(payload["snippet"]).strip() or None) if payload.get("snippet") else None,
        description=(
            str(payload["description"]).strip() or None
            if payload.get("description")
            else None
        ),
        symbols=symbols,
        entities=entities,
        image_url=(str(payload["image_url"]).strip() or None) if payload.get("image_url") else None,
    )


def fetch_news(symbol: str, limit: int) -> list[NewsArticle]:
    """Fetch and normalise recent Marketaux news for one ASX ticker."""
    if not settings.MARKETAUX_API_TOKEN:
        raise MarketauxError("MARKETAUX_API_TOKEN is not configured")

    request_limit = max(1, min(limit, 100))
    endpoint = f"{settings.MARKETAUX_BASE_URL.rstrip('/')}/news/all"
    try:
        response = httpx.get(
            endpoint,
            params={
                "api_token": settings.MARKETAUX_API_TOKEN,
                "symbols": marketaux_asx_symbol(symbol),
                "filter_entities": "true",
                "language": "en",
                "limit": request_limit,
            },
            timeout=30,
        )
    except httpx.RequestError as exc:
        raise MarketauxError("Could not connect to Marketaux") from exc

    if response.status_code >= 400:
        raise MarketauxError(f"Marketaux returned HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise MarketauxError("Marketaux returned invalid JSON") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise MarketauxError("Marketaux response did not contain a data list")

    return [normalise_article(item) for item in data if isinstance(item, dict)]


def article_content_hash(article: NewsArticle) -> str:
    """Build a stable provider-scoped hash from the article URL."""
    key = f"marketaux:url:{article.url.strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _get_or_create_ticker(db: Session, symbol: str):
    ticker_symbol = normalise_asx_symbol(symbol)
    ticker = ticker_crud.get_ticker_by_symbol(db, ticker_symbol)
    if ticker:
        return ticker
    return ticker_crud.create_ticker(
        db,
        TickerCreate(
            symbol=ticker_symbol,
            company_name=ticker_symbol,
            exchange="ASX",
        ),
    )


def _get_or_create_platform(db: Session):
    platform = platform_crud.get_platform_by_name(db, PROVIDER_NAME)
    if platform:
        return platform
    return platform_crud.create_platform(
        db,
        InformationPlatformCreate(
            name=PROVIDER_NAME,
            platform_type="news",
            base_url=settings.MARKETAUX_BASE_URL,
            scrape_enabled=True,
        ),
    )


def fetch_and_store_news(symbol: str, limit: int, db: Session) -> dict[str, Any]:
    """Fetch Marketaux articles and persist new ones as news artifacts."""
    articles = fetch_news(symbol, limit)
    ticker = _get_or_create_ticker(db, symbol)
    platform = _get_or_create_platform(db)
    result: dict[str, Any] = {
        "symbol": ticker.symbol,
        "found": len(articles),
        "created": 0,
        "summarised": 0,
        "skipped_duplicates": 0,
        "errors": 0,
        "error_details": [],
    }

    for article in articles:
        content_hash = article_content_hash(article)
        try:
            existing = artifact_crud.get_artifact_by_hash(db, content_hash)
            if existing:
                result["skipped_duplicates"] += 1
                if not news_summary.has_news_summary_metadata(existing):
                    try:
                        news_summary.summarise_news_artifact(db, existing)
                        result["summarised"] += 1
                    except Exception as exc:  # noqa: BLE001
                        db.rollback()
                        result["errors"] += 1
                        result["error_details"].append({
                            "url": article.url,
                            "stage": "summarise",
                            "message": str(exc),
                        })
                continue

            artifact = artifact_crud.create_artifact(
                db=db,
                artifact=ArtifactCreate(
                    source_type=SourceType.NEWS,
                    artifact_type=ArtifactType.NEWS_ARTICLE,
                    title=article.title,
                    url=article.url,
                    author=article.author,
                    raw_text=article.raw_text,
                    published_at=article.published_at or datetime.now(timezone.utc),
                    content_hash=content_hash,
                    ticker_id=ticker.id,
                    platform_id=platform.id,
                    artifact_metadata={
                        "provider": PROVIDER_KEY,
                        "provider_id": article.provider_id,
                        "source_name": article.source_name,
                        "text_used": article.text_used,
                        "snippet": article.snippet,
                        "description": article.description,
                        "symbols": article.symbols,
                        "entities": article.entities,
                        "image_url": article.image_url,
                    },
                ),
            )
            result["created"] += 1
            try:
                news_summary.summarise_news_artifact(db, artifact)
                result["summarised"] += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                result["errors"] += 1
                result["error_details"].append({
                    "url": article.url,
                    "stage": "summarise",
                    "message": str(exc),
                })
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result["errors"] += 1
            result["error_details"].append({
                "url": article.url,
                "stage": "store",
                "message": str(exc),
            })

    return result
