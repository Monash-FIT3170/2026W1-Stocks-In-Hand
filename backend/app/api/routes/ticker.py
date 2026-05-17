from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database.connection import get_db
from app.schemas.ticker import TickerCreate, TickerResponse
from app.crud import ticker as crud

router = APIRouter(prefix="/tickers", tags=["tickers"])

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
def get_mock_ticker_overview(symbol: str):
    return {
        "symbol": symbol.upper(),
        "company_name": f"{symbol.upper()} Group Limited",
        "sector": "Resources & Energy",
        "sentiment_label": "Generally Positive",
        "last_updated": "Just now",
        "current_price": "$74.20",
        "day_change": "+1.85%",
        "story": f"{symbol.upper()} exhibited strong operational resilience this quarter. Operational metrics remain well-positioned despite brief external sector pressures. Strategic initiatives continue ahead of schedule, prompting verified confidence from industry analysts.",
        "sources_count": 14,
        "public_sentiment_pct": "72%"
    }

@router.get("/symbol/{symbol}/news-feed")
def get_mock_ticker_news_feed(symbol: str):
    return [
        {
            "id": "mock-news-1",
            "ticker": symbol.upper(),
            "tag": "Earnings/Guidance",
            "time": "10:42 AM",
            "title": f"{symbol.upper()} Quarterly Performance Report",
            "about": f"Comprehensive review of operational performance, production pipelines, and core asset outputs for the active quarter.",
            "changed": "Core volumes scaled up 6% YoY; overall global margin guidance successfully maintained.",
            "matters": f"Strong organic volumes bolster cash generation capabilities; reinforces structural position within volatile market regimes.",
            "url": "https://www.asx.com.au"
        }
    ]

@router.get("/symbol/{symbol}/deep-dive-timeline")
def get_mock_ticker_deep_dive(symbol: str):
    return [
        {
            "month": "May 2026",
            "tag": "Strategic Update",
            "title": f"Expansion Feasibility Review",
            "date": "May 12, 2026",
            "detail": f"Board approvals finalized for modernizing operations. Capital allocations optimized to ensure maximum baseline efficiency enhancements.",
            "metrics": ["Capex $1.2B Allocated", "Target Efficiency +15%"],
            "tone": "green"
        },
        {
            "month": "Mar 2026",
            "tag": "Regulatory",
            "title": "Compliance Matrix Assessment",
            "date": "Mar 18, 2026",
            "detail": f"Routine review cycles completed alongside updated domestic operational protocols. Standard risk frameworks updated smoothly.",
            "metrics": ["100% Audit Complete"],
            "tone": "orange"
        }
    ]

