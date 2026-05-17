from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.models.artifact import Artifact
from app.models.claim import Claim
from app.models.claim_source import ClaimSource
from app.models.report import Report
from app.schemas.ticker import TickerCreate, TickerResponse
from app.crud import ticker as crud

router = APIRouter(prefix="/tickers", tags=["tickers"])


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


def _format_time(value):
    if not value:
        return "Time unavailable"
    return value.strftime("%I:%M %p").lstrip("0")


def _format_month(value):
    if not value:
        return "Recent"
    return value.strftime("%b %Y")


def _format_date(value):
    if not value:
        return "Date unavailable"
    return value.strftime("%b %d, %Y")


def _format_label(value, fallback):
    cleaned = _clean_text(value) or fallback
    return cleaned.replace("_", " ").replace("-", " ").title()


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


def _source_from_claim_source(source):
    artifact = source.artifact
    return _source_from_values(
        label=_format_label(artifact.source_type if artifact else None, "Source"),
        title=(artifact.title if artifact else None) or source.evidence_text,
        url=source.url or (artifact.url if artifact else None),
        published_at=source.published_at or (artifact.published_at if artifact else None),
        evidence_text=source.evidence_text,
    )


def _sources_for_ticker(db, ticker_id, limit=4):
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


def _sources_for_artifact(artifact):
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


def _mock_sources(symbol):
    ticker = symbol.upper()
    return [
        {
            "label": "ASX Filing",
            "title": f"{ticker} quarterly performance report",
            "url": "https://www.asx.com.au/markets/company/BHP",
            "published_at": None,
            "evidence_text": "Mock citation used until ticker source data is available in the database.",
        },
        {
            "label": "Market Update",
            "title": f"{ticker} sector briefing",
            "url": "https://www.asx.com.au/",
            "published_at": None,
            "evidence_text": "Fallback source for frontend citation display in empty development databases.",
        },
    ]


def _mock_overview(symbol):
    ticker = symbol.upper()
    sources = _mock_sources(ticker)
    return {
        "symbol": ticker,
        "company_name": f"{ticker} Group Limited",
        "sector": "Resources & Energy",
        "sentiment_label": "Generally Positive",
        "last_updated": "Just now",
        "current_price": "$74.20",
        "day_change": "+1.85%",
        "story": f"{ticker} exhibited strong operational resilience this quarter. Operational metrics remain well-positioned despite brief external sector pressures. Strategic initiatives continue ahead of schedule, prompting verified confidence from industry analysts.",
        "sources_count": len(sources),
        "public_sentiment_pct": "72%",
        "sources": sources,
    }


def _mock_news(symbol):
    ticker = symbol.upper()
    sources = _mock_sources(ticker)
    return [
        {
            "id": "mock-news-1",
            "ticker": ticker,
            "tag": "Earnings/Guidance",
            "time": "10:42 AM",
            "title": f"{ticker} Quarterly Performance Report",
            "about": "Comprehensive review of operational performance, production pipelines, and core asset outputs for the active quarter.",
            "changed": "Core volumes scaled up 6% YoY; overall global margin guidance successfully maintained.",
            "matters": "Strong organic volumes bolster cash generation capabilities; reinforces structural position within volatile market regimes.",
            "url": sources[0]["url"],
            "sources": sources,
        }
    ]


def _mock_deep_dive(symbol):
    ticker = symbol.upper()
    sources = _mock_sources(ticker)
    return [
        {
            "month": "May 2026",
            "tag": "Strategic Update",
            "title": "Expansion Feasibility Review",
            "date": "May 12, 2026",
            "detail": "Board approvals finalized for modernizing operations. Capital allocations optimized to ensure maximum baseline efficiency enhancements.",
            "metrics": ["Capex $1.2B Allocated", "Target Efficiency +15%"],
            "tone": "green",
            "sources": sources,
        },
        {
            "month": "Mar 2026",
            "tag": "Regulatory",
            "title": "Compliance Matrix Assessment",
            "date": "Mar 18, 2026",
            "detail": "Routine review cycles completed alongside updated domestic operational protocols. Standard risk frameworks updated smoothly.",
            "metrics": ["100% Audit Complete"],
            "tone": "orange",
            "sources": sources[:1],
        },
    ]

@router.post("/", response_model=TickerResponse)
def create_ticker(ticker: TickerCreate, db: Session = Depends(get_db)):
    existing = crud.get_ticker_by_symbol(db, symbol=ticker.symbol)
    if existing:
        raise HTTPException(status_code=400, detail="Ticker symbol already exists")
    return crud.create_ticker(db=db, ticker=ticker)

@router.get("/", response_model=list[TickerResponse])
def get_tickers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_tickers(db, skip=skip, limit=limit)

@router.get("/symbol/{symbol}", response_model=TickerResponse)
def get_ticker_by_symbol(symbol: str, db: Session = Depends(get_db)):
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
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        return _mock_overview(symbol)

    report = (
        db.query(Report)
        .filter(Report.ticker_id == ticker.id)
        .order_by(Report.generated_at.desc())
        .first()
    )
    sources = _sources_for_ticker(db, ticker.id)
    if not sources:
        sources = _mock_sources(ticker.symbol)

    return {
        "symbol": ticker.symbol,
        "company_name": ticker.company_name,
        "sector": ticker.sector or ticker.industry or ticker.exchange,
        "sentiment_label": "Generally Positive",
        "last_updated": "Just now",
        "current_price": "$74.20",
        "day_change": "+1.85%",
        "story": _preview(report.report_text, 520) if report else _mock_overview(ticker.symbol)["story"],
        "sources_count": len(sources),
        "public_sentiment_pct": "72%",
        "sources": sources,
    }

@router.get("/symbol/{symbol}/news-feed")
def get_ticker_news_feed(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        return _mock_news(symbol)

    artifacts = (
        db.query(Artifact)
        .options(joinedload(Artifact.claim_sources).joinedload(ClaimSource.artifact))
        .filter(Artifact.ticker_id == ticker.id)
        .filter((Artifact.is_duplicate.is_(False)) | (Artifact.is_duplicate.is_(None)))
        .order_by(func.coalesce(Artifact.published_at, Artifact.created_at).desc())
        .limit(10)
        .all()
    )
    if not artifacts:
        return _mock_news(ticker.symbol)

    items = []
    for artifact in artifacts:
        metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
        title = _clean_text(artifact.title) or "Untitled update"
        about = _clean_text(metadata.get("about")) or _preview(artifact.raw_text) or title
        changed = _clean_text(metadata.get("changed")) or _clean_text(metadata.get("what_changed")) or "No change summary available yet."
        matters = _clean_text(metadata.get("matters")) or _clean_text(metadata.get("why_it_matters")) or "No impact summary available yet."
        sources = _sources_for_artifact(artifact) or _mock_sources(ticker.symbol)
        items.append(
            {
                "id": str(artifact.id),
                "ticker": ticker.symbol,
                "tag": _format_label(metadata.get("category"), artifact.artifact_type),
                "time": _format_time(artifact.published_at or artifact.created_at),
                "title": title,
                "about": about,
                "changed": changed,
                "matters": matters,
                "url": sources[0]["url"] if sources else artifact.url,
                "sources": sources,
            }
        )
    return items

@router.get("/symbol/{symbol}/deep-dive-timeline")
def get_ticker_deep_dive(symbol: str, db: Session = Depends(get_db)):
    ticker = crud.get_ticker_by_symbol(db, symbol=symbol.upper())
    if not ticker:
        return _mock_deep_dive(symbol)

    artifacts = (
        db.query(Artifact)
        .options(joinedload(Artifact.claim_sources).joinedload(ClaimSource.artifact))
        .filter(Artifact.ticker_id == ticker.id)
        .filter((Artifact.is_duplicate.is_(False)) | (Artifact.is_duplicate.is_(None)))
        .order_by(func.coalesce(Artifact.published_at, Artifact.created_at).desc())
        .limit(8)
        .all()
    )
    if not artifacts:
        return _mock_deep_dive(ticker.symbol)

    timeline = []
    for artifact in artifacts:
        metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
        event_date = artifact.published_at or artifact.created_at
        sources = _sources_for_artifact(artifact) or _mock_sources(ticker.symbol)
        timeline.append(
            {
                "month": _format_month(event_date),
                "tag": _format_label(metadata.get("category"), artifact.artifact_type),
                "title": _clean_text(artifact.title) or "Ticker update",
                "date": _format_date(event_date),
                "detail": _preview(artifact.raw_text, 360) or "No detail summary available yet.",
                "metrics": metadata.get("metrics") if isinstance(metadata.get("metrics"), list) else [],
                "tone": "green",
                "sources": sources,
            }
        )
    return timeline
