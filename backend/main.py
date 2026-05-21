"""
main python file which creates database connection, connects to finBERT, and runs a FastAPI server
"""
import asyncio
from datetime import date, timedelta

import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright
from app.models.information_platform import InformationPlatform
from pathlib import Path
from app.services import sentiment as sentiment_service

# Import from app structure
from app.api.routes import (
    investor,
    ticker,
    watchlist,
    watchlist_ticker,
    alert,
    report,
    artifact,
    artifact_chunk,
    artifact_summary,
    artifact_sentiment,
    artifact_topic,
    extracted_fact,
    claim,
    claim_source,
    report_claim,
    llm_run,
    scrape_run,
    market_data,
    information_platform,
    topic,
    reddit,
    gemini,
    category_sentiment,
    auth,
    announcement,
)
from app.database.connection import SessionLocal
from app.core.config import settings
from app.models.result import Result

# Import scrapers
from scrapers.registry import scrape, available_tickers

app = FastAPI(title="StonksInHand API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all database routes
app.include_router(investor.router)
app.include_router(ticker.router)
app.include_router(watchlist.router)
app.include_router(watchlist_ticker.router)
app.include_router(alert.router)
app.include_router(report.router)
app.include_router(artifact.router)
app.include_router(artifact_chunk.router)
app.include_router(artifact_summary.router)
app.include_router(artifact_sentiment.router)
app.include_router(artifact_topic.router)
app.include_router(extracted_fact.router)
app.include_router(claim.router)
app.include_router(claim_source.router)
app.include_router(report_claim.router)
app.include_router(llm_run.router)
app.include_router(scrape_run.router)
app.include_router(market_data.router)
app.include_router(information_platform.router)
app.include_router(topic.router)
app.include_router(auth.router)
app.include_router(reddit.router)
app.include_router(gemini.router)
app.include_router(category_sentiment.router)
app.include_router(announcement.router)

@app.on_event("startup")
def seed_platforms():
    with SessionLocal() as db:
        exists = db.query(InformationPlatform).filter(
            InformationPlatform.name == "Reddit"
        ).first()
        if not exists:
            db.add(InformationPlatform(
                name="Reddit",
                platform_type="social",
                base_url="https://reddit.com",
                scrape_enabled=True,
            ))
            db.commit()


async def _fetch_market_data(symbol: str) -> None:
    from app.crud import ticker as ticker_crud
    from app.crud import market_data as market_data_crud

    yahoo_symbol = f"{symbol}.AX"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            print(f"[SEED] Yahoo Finance returned {resp.status_code} for {symbol}")
            return
        result = resp.json().get("chart", {}).get("result") or []
        if not result:
            print(f"[SEED] No chart data from Yahoo Finance for {symbol}")
            return
        meta = result[0].get("meta", {})
        current_price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("regularMarketPreviousClose")
        if not current_price:
            print(f"[SEED] Could not parse price for {symbol}")
            return
        today = date.today()
        with SessionLocal() as db:
            ticker_obj = ticker_crud.get_ticker_by_symbol(db, symbol=symbol)
            if ticker_obj:
                market_data_crud.upsert_market_data(
                    db, ticker_id=ticker_obj.id, price_date=today, close_price=current_price
                )
                if prev_close:
                    market_data_crud.upsert_market_data(
                        db,
                        ticker_id=ticker_obj.id,
                        price_date=today - timedelta(days=1),
                        close_price=prev_close,
                    )
                print(f"[SEED] Market data for {symbol}: ${current_price} (prev: ${prev_close})")
    except Exception as exc:
        print(f"[SEED] Market data fetch for {symbol} failed: {exc}")


async def _run_seed(tickers: list[str]) -> None:
    import sys as _sys
    import traceback as _traceback
    from pathlib import Path as _Path

    parsing_dir = str(_Path(__file__).parent / "parsing")
    if parsing_dir not in _sys.path:
        _sys.path.insert(0, parsing_dir)

    from scrapers.registry import scrape
    from pipeline import process_announcement

    output_dir = _Path("/app/output")

    print(f"[SEED] Auto-seeding tickers: {', '.join(tickers)}")
    for symbol in tickers:
        print(f"[SEED] Processing {symbol}...")
        try:
            announcements = await scrape(symbol, output_dir)
            print(f"[SEED] {symbol}: {len(announcements)} announcements scraped")
            loop = asyncio.get_event_loop()
            for ann in announcements:
                if not ann.local_path:
                    print(f"[SEED] {symbol}: skipping '{ann.title[:50]}' — PDF not downloaded")
                    continue
                await loop.run_in_executor(None, process_announcement, ann)
            print(f"[SEED] {symbol} pipeline complete.")
        except Exception as exc:
            print(f"[SEED] {symbol} failed: {exc}")
            _traceback.print_exc()
        await _fetch_market_data(symbol)
    print("[SEED] Auto-seed finished.")


@app.on_event("startup")
async def auto_seed():
    if not settings.SEED_TICKERS:
        return
    asyncio.ensure_future(_run_seed(settings.SEED_TICKERS))


OUTPUT_DIR = Path("/app/output")

@app.get("/")
def root():
    return {
        "message": "StonksInHand FastAPI backend",
        "frontend": "http://localhost:3000",
        "docs": "/docs",
        "health": "/health",
        "endpoints": ["/analyse", "/sentiment/{ticker}", "/headlines", "/results", "/scrape/{ticker}", "/tickers",],
    }

@app.get("/health")
def health() -> dict:
    """Returns the health status of the server"""
    return {"status": "ok"}

@app.get("/viewer", response_class=HTMLResponse)
def viewer():
    return (Path(__file__).parent / "viewer.html").read_text(encoding="utf-8")

# --- Playwright scraper ---
async def scrape_yahoo_headlines(ticker: str = "BHP.AX") -> list[str]:
    """
    Scrapes Yahoo for headlines relating to a ticker

    Keyword arguments:
    ticker -- a string representing the ticker of a company

    Returns:
    a list of 10 headlines (strings) relating to the ticker that was input
    """
    url = f"https://finance.yahoo.com/quote/{ticker}/news/"
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--headless=new"],
        )
        page = await browser.new_page()
        await page.goto(url, timeout=15000)
        await page.wait_for_load_state("domcontentloaded")

        # grab all h3 text on the page, filter out short/nav ones
        items = await page.query_selector_all("h3")
        headline_list = []
        for item in items[:30]:
            text = (await item.inner_text()).strip()
            if len(text) > 20:  # filter out nav labels like "Trending Tickers"
                headline_list.append(text)

        await browser.close()
    return headline_list[:10]

# --- API ---

class AnalyseRequest(BaseModel):
    """Class representing the structure of requests made to the analyse API"""
    text: str

@app.post("/analyse")
def analyse(body: AnalyseRequest) -> dict:
    """Analyses the sentiment of a headline passed in as an AnalyseRequest"""
    out = sentiment_service.analyse_text(body.text)
    with SessionLocal() as db:
        row = Result(
            text=body.text,
            label=out["sentiment_label"],
            score=out["score"],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return {"id": row.id, "label": row.label, "score": row.score}

@app.get("/results")
def results() -> list[dict]:
    """Returns a list of sentiment analysis results"""
    with SessionLocal() as db:
        rows = db.query(Result).order_by(Result.id.desc()).limit(10).all()
    return [{"id": r.id, "text": r.text[:80], "label": r.label, "score": r.score} for r in rows]

@app.get("/headlines")
async def headlines() -> list[str]:
    """Returns a list of headlines from Yahoo for the default ticker"""
    return await scrape_yahoo_headlines()

@app.post("/scrape/{ticker}")
async def scrape_ticker(ticker: str, background_tasks: BackgroundTasks):
    """
    Trigger an ASX announcement scrape for a given ticker.
    Runs in the background — returns immediately.
    PDFs are saved to /app/output/{ticker}/
    """
    if ticker.upper() not in available_tickers():
        raise HTTPException(
            status_code=404,
            detail=f"'{ticker.upper()}' not implemented. Available: {available_tickers()}"
        )
    background_tasks.add_task(scrape, ticker, OUTPUT_DIR)
    return {"status": "queued", "ticker": ticker.upper()}

@app.get("/tickers")
def tickers():
    """Return all implemented ASX tickers."""
    return {"tickers": available_tickers()}
