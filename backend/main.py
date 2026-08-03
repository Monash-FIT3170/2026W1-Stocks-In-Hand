"""
main python file which creates database connection, connects to finBERT, and runs a FastAPI server
"""
import asyncio
from pathlib import Path

from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright

from app.models.information_platform import InformationPlatform
from app.services import sentiment as sentiment_service

from app.api.routes import (
    investor,
    ticker,
    watchlist,
    watchlist_ticker,
    artifact,
    artifact_summary,
    artifact_sentiment,
    scrape_run,
    information_platform,
    reddit,
    gemini,
    category_sentiment,
    auth,
    announcement,
)
from app.database.connection import SessionLocal, get_db
from app.core.config import settings

from scrapers.registry import scrape, available_tickers

app = FastAPI(title="StonksInHand API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(investor.router)
app.include_router(ticker.router)
app.include_router(watchlist.router)
app.include_router(watchlist_ticker.router)
app.include_router(artifact.router)
app.include_router(artifact_summary.router)
app.include_router(artifact_sentiment.router)
app.include_router(scrape_run.router)
app.include_router(information_platform.router)
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


def _run_seed_sentiment(symbol: str) -> None:
    with SessionLocal() as db:
        try:
            result = category_sentiment.build_ticker_category_sentiment(
                ticker=symbol,
                body=None,
                db=db,
                persist=True,
            )
            categories = ", ".join(result["categories"].keys())
            print(f"[SEED] Sentiment for {symbol}: {categories}")
        except Exception as exc:
            print(f"[SEED] Sentiment analysis for {symbol} skipped: {exc}")


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
    loop = asyncio.get_event_loop()

    print(f"[SEED] Auto-seeding tickers: {', '.join(tickers)}")
    for symbol in tickers:
        print(f"[SEED] Processing {symbol}...")
        try:
            announcements = await scrape(symbol, output_dir)
            print(f"[SEED] {symbol}: {len(announcements)} announcements scraped")
            for ann in announcements:
                if not ann.local_path:
                    print(f"[SEED] {symbol}: skipping '{ann.title[:50]}' — PDF not downloaded")
                    continue
                await loop.run_in_executor(None, process_announcement, ann)
            print(f"[SEED] {symbol} pipeline complete.")
        except Exception as exc:
            print(f"[SEED] {symbol} failed: {exc}")
            _traceback.print_exc()
        await loop.run_in_executor(None, _run_seed_sentiment, symbol)
    print("[SEED] Auto-seed finished.")


async def _run_reddit_seed() -> None:
    if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
        print("[REDDIT] Startup scrape skipped: Reddit credentials are not configured")
        return

    subreddit = settings.REDDIT_SEED_SUBREDDIT
    limit = max(settings.REDDIT_SEED_LIMIT, 1)
    print(f"[REDDIT] Startup scrape queued for r/{subreddit} (limit={limit})")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            reddit._scrape_and_store_posts,
            subreddit,
            limit,
        )
        print(
            "[REDDIT] Startup scrape complete "
            f"r/{subreddit}: saved={result['saved']} skipped={result['skipped_duplicates']}"
        )
    except Exception as exc:
        print(f"[REDDIT] Startup scrape failed for r/{subreddit}: {exc}")


@app.on_event("startup")
async def auto_seed():
    if not settings.SEED_TICKERS:
        return
    asyncio.ensure_future(_run_seed(settings.SEED_TICKERS))


@app.on_event("startup")
async def auto_seed_reddit():
    asyncio.ensure_future(_run_reddit_seed())


OUTPUT_DIR = Path("/app/output")

@app.get("/")
def root():
    return {
        "message": "StonksInHand FastAPI backend",
        "frontend": "http://localhost:3000",
        "docs": "/docs",
        "health": "/health",
        "endpoints": ["/analyse", "/sentiment/{ticker}", "/headlines", "/scrape/{ticker}", "/tickers"],
    }

@app.get("/health")
def health() -> dict:
    """Returns the health status of the server"""
    return {"status": "ok"}

@app.get("/viewer", response_class=HTMLResponse)
def viewer():
    return (Path(__file__).parent / "viewer.html").read_text(encoding="utf-8")

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

        items = await page.query_selector_all("h3")
        headline_list = []
        for item in items[:30]:
            text = (await item.inner_text()).strip()
            if len(text) > 20:
                headline_list.append(text)

        await browser.close()
    return headline_list[:10]


class AnalyseRequest(BaseModel):
    """Class representing the structure of requests made to the analyse API"""
    text: str

@app.post("/analyse")
def analyse(body: AnalyseRequest) -> dict:
    """Analyses the sentiment of a headline passed in as an AnalyseRequest"""
    out = sentiment_service.analyse_text(body.text)
    return {"label": out["sentiment_label"], "score": out["score"]}

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
def tickers(skip: int = 0, limit: int = 100, db=Depends(get_db)):
    """Return database tickers for clients that request /tickers without a slash."""
    return ticker.get_tickers(skip=skip, limit=limit, db=db)
