import re
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from uuid import UUID

from app.crud import market_data as market_data_crud
from app.crud import ticker as crud
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.artifact_sentiment import ArtifactSentiment
from app.models.artifact_summary import ArtifactSummary
from app.models.claim import Claim
from app.models.claim_source import ClaimSource
from app.models.market_data import MarketData
from app.models.ticker import Ticker
from app.schemas.ticker import TickerCreate, TickerResponse

router = APIRouter(prefix="/tickers", tags=["tickers"])

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")
DEFAULT_TICKERS = {
    "ANZ": {
        "company_name": "ANZ Group Holdings Limited",
        "exchange": "ASX",
        "sector": "Financials",
        "industry": "Banks",
    },
    "BHP": {
        "company_name": "BHP Group Limited",
        "exchange": "ASX",
        "sector": "Materials",
        "industry": "Diversified Metals & Mining",
    },
    "CBA": {
        "company_name": "Commonwealth Bank of Australia",
        "exchange": "ASX",
        "sector": "Financials",
        "industry": "Banks",
    },
    "CSL": {
        "company_name": "CSL Limited",
        "exchange": "ASX",
        "sector": "Health Care",
        "industry": "Biotechnology",
    },
    "WES": {
        "company_name": "Wesfarmers Limited",
        "exchange": "ASX",
        "sector": "Consumer Discretionary",
        "industry": "Consumer Staples Distribution & Retail",
    },
}


def _ensure_default_tickers(db: Session) -> None:
    changed = False

    for symbol, defaults in DEFAULT_TICKERS.items():
        ticker = crud.get_ticker_by_symbol(db, symbol=symbol)
        if not ticker:
            db.add(Ticker(symbol=symbol, **defaults))
            changed = True
            continue

        for key, value in defaults.items():
            current = getattr(ticker, key)
            if not current or (key == "company_name" and current == symbol):
                setattr(ticker, key, value)
                changed = True

    if changed:
        db.commit()


def _money(value) -> str:
    if value is None:
        return "N/A"
    return f"${float(value):,.2f}"


def _latest_market_rows(db: Session, ticker_id: UUID) -> list[MarketData]:
    return (
        db.query(MarketData)
        .filter(MarketData.ticker_id == ticker_id)
        .order_by(MarketData.price_date.desc())
        .limit(2)
        .all()
    )


def _fetch_market_rows_if_missing(db: Session, ticker: Ticker) -> list[MarketData]:
    rows = _latest_market_rows(db, ticker.id)
    if rows or ticker.symbol not in DEFAULT_TICKERS:
        return rows

    yahoo_symbol = f"{ticker.symbol}.AX"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"

    try:
        with httpx.Client(timeout=6) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        result = response.json().get("chart", {}).get("result") or []
        if not result:
            return rows

        meta = result[0].get("meta", {})
        current_price = meta.get("regularMarketPrice")
        previous_close = meta.get("chartPreviousClose") or meta.get(
            "regularMarketPreviousClose"
        )
        if current_price is None:
            return rows

        today = date.today()
        market_data_crud.upsert_market_data(
            db,
            ticker_id=ticker.id,
            price_date=today,
            close_price=current_price,
        )
        if previous_close is not None:
            market_data_crud.upsert_market_data(
                db,
                ticker_id=ticker.id,
                price_date=today - timedelta(days=1),
                close_price=previous_close,
            )
        return _latest_market_rows(db, ticker.id)
    except Exception:
        return rows


def _day_change(rows: list[MarketData]) -> str:
    if len(rows) < 2 or rows[0].close_price is None or rows[1].close_price is None:
        return "N/A"
    previous = float(rows[1].close_price)
    if previous == 0:
        return "N/A"
    change = ((float(rows[0].close_price) - previous) / previous) * 100
    return f"{change:+.2f}%"


def _sentiment_label(value: str | None) -> str:
    labels = {
        "positive": "Generally Positive",
        "negative": "Generally Negative",
        "neutral": "Neutral",
    }
    return labels.get((value or "").lower(), "Neutral")


def _clean_text(value):
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _preview(value, max_length=220):
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[:max_length].rstrip()}..."


def _metadata_value(artifact: Artifact, key: str, fallback: str) -> str:
    metadata = artifact.artifact_metadata or {}
    return _clean_text(metadata.get(key)) or fallback


def _format_announcement_time(artifact: Artifact) -> str:
    if artifact.published_at:
        return f"{artifact.published_at.strftime('%b')} {artifact.published_at.day}, {artifact.published_at.year}"
    return "Recently"


def _format_month(value):
    if not value:
        return "Recent"
    return value.strftime("%b %Y")


def _format_label(value, fallback):
    cleaned = _clean_text(value) or fallback
    label = cleaned.replace("_", " ").replace("-", " ")
    label = _CAMEL_BOUNDARY.sub(" ", label)
    return label.title()


def _format_key_date(value):
    if not value:
        return "No filings yet"
    return value.strftime("%b %Y")


def _source_from_values(label, title, url, published_at=None, evidence_text=None):
    cleaned_url = _clean_text(url)
    if not cleaned_url:
        return None
    return {
        "label": label,
        "title": _clean_text(title) or label,
        "url": cleaned_url,
        "published_at": published_at.isoformat() if published_at else None,
        "evidence_text": _preview(evidence_text, 180),
    }


def _source_from_claim_source(source: ClaimSource):
    artifact = source.artifact
    return _source_from_values(
        label=_format_label(artifact.source_type if artifact else None, "Source"),
        title=(artifact.title if artifact else None) or source.evidence_text,
        url=source.url or (artifact.url if artifact else None),
        published_at=source.published_at or (artifact.published_at if artifact else None),
        evidence_text=source.evidence_text,
    )


def _sources_for_ticker(db: Session, ticker_id: UUID, limit: int = 4):
    sources = (
        db.query(ClaimSource)
        .join(Claim, ClaimSource.claim_id == Claim.id)
        .options(joinedload(ClaimSource.artifact))
        .filter(Claim.ticker_id == ticker_id)
        .order_by(ClaimSource.created_at.desc())
        .limit(limit)
        .all()
    )
    return [item for item in (_source_from_claim_source(source) for source in sources) if item]


def _sources_for_artifact(artifact: Artifact):
    sources = [
        item
        for item in (
            _source_from_claim_source(source)
            for source in sorted(
                artifact.claim_sources,
                key=lambda source: source.published_at or source.created_at,
                reverse=True,
            )
        )
        if item
    ]
    artifact_source = _source_from_values(
        label=_format_label(artifact.source_type, "Source"),
        title=artifact.title,
        url=artifact.url,
        published_at=artifact.published_at or artifact.created_at,
        evidence_text=artifact.raw_text,
    )
    if artifact_source and not any(source["url"] == artifact_source["url"] for source in sources):
        sources.append(artifact_source)
    return sources


def _ticker_artifacts(db: Session, ticker_id: UUID, limit: int = 10) -> list[Artifact]:
    return (
        db.query(Artifact)
        .options(joinedload(Artifact.claim_sources).joinedload(ClaimSource.artifact))
        .filter(Artifact.ticker_id == ticker_id)
        .filter((Artifact.is_duplicate.is_(False)) | (Artifact.is_duplicate.is_(None)))
        .order_by(Artifact.published_at.desc().nullslast(), Artifact.created_at.desc())
        .limit(limit)
        .all()
    )


def _latest_sentiment_for_ticker(db: Session, ticker_id: UUID) -> ArtifactSentiment | None:
    return (
        db.query(ArtifactSentiment)
        .join(Artifact, ArtifactSentiment.artifact_id == Artifact.id)
        .filter(Artifact.ticker_id == ticker_id)
        .filter((Artifact.is_duplicate.is_(False)) | (Artifact.is_duplicate.is_(None)))
        .order_by(ArtifactSentiment.created_at.desc())
        .first()
    )


def _claims_for_ticker(db: Session, ticker_id: UUID, limit: int = 6) -> dict[str, list[str]]:
    rows = (
        db.query(Claim)
        .join(ClaimSource, ClaimSource.claim_id == Claim.id)
        .filter(Claim.ticker_id == ticker_id)
        .order_by(Claim.created_at.desc())
        .limit(limit)
        .all()
    )

    confirmed: list[str] = []
    rumoured: list[str] = []
    seen: set[UUID] = set()
    rumour_labels = {"rumoured", "rumored", "unverified", "low"}

    for claim in rows:
        if claim.id in seen:
            continue
        seen.add(claim.id)
        text = _clean_text(claim.claim_text)
        if not text:
            continue
        label = (claim.reliability_label or "").lower()
        if label in rumour_labels:
            rumoured.append(text)
        else:
            confirmed.append(text)

    return {"confirmed": confirmed, "rumoured": rumoured}


def _themes_from_artifacts(artifacts: list[Artifact], limit: int = 5) -> list[str]:
    themes: list[str] = []
    seen: set[str] = set()

    for artifact in artifacts:
        metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
        label = _format_label(metadata.get("category"), artifact.artifact_type)
        if label.lower() == "unknown":
            label = _format_label(artifact.artifact_type, "Announcement")
        theme = f"{label} activity"
        key = theme.lower()
        if key not in seen:
            themes.append(theme)
            seen.add(key)
        if len(themes) >= limit:
            break

    return themes


@router.post("/", response_model=TickerResponse)
def create_ticker(ticker: TickerCreate, db: Session = Depends(get_db)):
    existing = crud.get_ticker_by_symbol(db, symbol=ticker.symbol)
    if existing:
        raise HTTPException(status_code=400, detail="Ticker symbol already exists")
    return crud.create_ticker(db=db, ticker=ticker)


@router.get("/", response_model=list[TickerResponse])
def get_tickers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    _ensure_default_tickers(db)
    return crud.get_tickers(db, skip=skip, limit=limit)


@router.get("/symbol/{symbol}", response_model=TickerResponse)
def get_ticker_by_symbol(symbol: str, db: Session = Depends(get_db)):
    _ensure_default_tickers(db)
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker


@router.get("/{ticker_id}", response_model=TickerResponse)
def get_ticker(ticker_id: UUID, db: Session = Depends(get_db)):
    ticker = crud.get_ticker(db, ticker_id=ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker


@router.patch("/{ticker_id}", response_model=TickerResponse)
def update_ticker(ticker_id: UUID, data: dict, db: Session = Depends(get_db)):
    ticker = crud.get_ticker(db, ticker_id=ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return crud.update_ticker(db=db, ticker_id=ticker_id, data=data)


@router.get("/symbol/{symbol}/overview")
def get_ticker_overview(symbol: str, db: Session = Depends(get_db)):
    _ensure_default_tickers(db)
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    market_rows = _fetch_market_rows_if_missing(db, ticker)
    latest_price = market_rows[0].close_price if market_rows else None
    artifacts = _ticker_artifacts(db, ticker.id, limit=20)
    latest_artifact = artifacts[0] if artifacts else None
    latest_sentiment = _latest_sentiment_for_ticker(db, ticker.id)

    story = (
        _metadata_value(latest_artifact, "about", _preview(latest_artifact.raw_text, 240))
        if latest_artifact and latest_artifact.raw_text
        else (
            f"{ticker.symbol} is tracked from the StonksInHand database. "
            "Add announcements and analysis data to enrich this brief."
        )
    )
    sources = _sources_for_ticker(db, ticker.id)
    if not sources and latest_artifact:
        sources = _sources_for_artifact(latest_artifact)

    return {
        "symbol": ticker.symbol,
        "company_name": ticker.company_name,
        "sector": ticker.sector or ticker.industry or ticker.exchange,
        "sentiment_label": _sentiment_label(
            latest_sentiment.sentiment_label if latest_sentiment else None
        ),
        "last_updated": (
            _format_announcement_time(latest_artifact)
            if latest_artifact
            else "No updates yet"
        ),
        "current_price": _money(latest_price),
        "day_change": _day_change(market_rows),
        "story": story,
        "sources_count": len(sources) if sources else len(artifacts),
        "public_sentiment_pct": (
            f"{round(float(latest_sentiment.confidence_score or 0) * 100)}%"
            if latest_sentiment
            else "N/A"
        ),
        "sources": sources,
    }


@router.get("/symbol/{symbol}/brief-aside")
def get_ticker_brief_aside(symbol: str, db: Session = Depends(get_db)):
    _ensure_default_tickers(db)
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    market_rows = _fetch_market_rows_if_missing(db, ticker)
    latest_price = market_rows[0].close_price if market_rows else None
    artifacts = _ticker_artifacts(db, ticker.id, limit=20)
    latest_artifact = artifacts[0] if artifacts else None

    return {
        "key_numbers": [
            {"label": "Current price", "value": _money(latest_price)},
            {"label": "Day change", "value": _day_change(market_rows)},
            {
                "label": "Latest filing",
                "value": _format_key_date(
                    latest_artifact.published_at if latest_artifact else None
                ),
            },
            {
                "label": "Latest type",
                "value": (
                    _format_label(
                        _metadata_value(
                            latest_artifact,
                            "category",
                            latest_artifact.artifact_type,
                        ),
                        latest_artifact.artifact_type,
                    )
                    if latest_artifact
                    else "No filings yet"
                ),
            },
        ],
        "market_intelligence": _claims_for_ticker(db, ticker.id),
        "themes": _themes_from_artifacts(artifacts),
    }


@router.get("/symbol/{symbol}/news-feed")
def get_ticker_news_feed(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    artifacts = _ticker_artifacts(db, ticker.id)
    return [
        {
            "id": str(artifact.id),
            "ticker": ticker.symbol,
            "tag": _format_label(
                _metadata_value(
                    artifact,
                    "category",
                    artifact.source_type or artifact.artifact_type,
                ),
                artifact.artifact_type,
            ),
            "time": _format_announcement_time(artifact),
            "title": artifact.title or f"{ticker.symbol} announcement",
            "about": _metadata_value(
                artifact,
                "about",
                _metadata_value(
                    artifact,
                    "summary",
                    _preview(artifact.raw_text, 160) or "No summary available yet.",
                ),
            ),
            "changed": _metadata_value(artifact, "changed", "No change summary available yet."),
            "matters": _metadata_value(artifact, "matters", "No investment impact summary available yet."),
            "url": artifact.url,
            "sources": _sources_for_artifact(artifact),
        }
        for artifact in artifacts
    ]


@router.get("/symbol/{symbol}/deep-dive-timeline")
def get_ticker_deep_dive_timeline(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    artifacts = _ticker_artifacts(db, ticker.id)
    timeline = []
    for artifact in artifacts:
        summary = (
            db.query(ArtifactSummary)
            .filter(ArtifactSummary.artifact_id == artifact.id)
            .order_by(ArtifactSummary.created_at.desc())
            .first()
        )
        timeline.append(
            {
                "month": _format_month(artifact.published_at),
                "tag": _format_label(
                    _metadata_value(artifact, "category", artifact.artifact_type),
                    artifact.artifact_type,
                ),
                "title": artifact.title or f"{ticker.symbol} update",
                "date": _format_announcement_time(artifact),
                "detail": (
                    summary.summary_text
                    if summary
                    else (
                        _preview(artifact.raw_text, 240)
                        if artifact.raw_text
                        else "No detail available yet."
                    )
                ),
                "metrics": [f"Source: {artifact.source_type or artifact.artifact_type}"],
                "tone": "green" if artifact.credibility_label == "official" else "orange",
                "sources": _sources_for_artifact(artifact),
            }
        )

    if timeline:
        return timeline

    return [
        {
            "month": "Recent",
            "tag": "Database",
            "title": f"{ticker.symbol} profile created",
            "date": "No announcements yet",
            "detail": (
                f"{ticker.company_name} exists in the database, "
                "but no announcement timeline has been loaded yet."
            ),
            "metrics": [ticker.exchange],
            "tone": "green",
            "sources": [],
        }
    ]
