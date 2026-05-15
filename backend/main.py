"""
main python file which creates database connection, connects to finBERT, and runs a FastAPI server
"""
import os
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from transformers import pipeline
from playwright.async_api import async_playwright
from pathlib import Path

# Import from app structure (from INCOMING/main branch)
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
    reddit
)
from app.database.connection import SessionLocal
from app.models.result import Result

# Import scrapers (from CURRENT/your branch)
from scrapers.registry import scrape, available_tickers

app = FastAPI(title="Spike API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Register all database routes (from INCOMING)
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
app.include_router(reddit.router)

OUTPUT_DIR = Path("/app/output")

@app.get("/")
def root():
    return {
        "message": "StonksInHand FastAPI backend",
        "frontend": "http://localhost:3000",
        "docs": "/docs",
        "health": "/health",
        "endpoints": ["/analyse", "/headlines", "/results", "/scrape/{ticker}", "/tickers"],
    }

@app.get("/health")
def health() -> dict:
    """Returns the health status of the server"""
    return {"status": "ok"}

# --- HuggingFace: FinBERT ---
sentiment = pipeline("text-classification", model="/app/finbert")

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
            executable_path="/usr/bin/chromium",
            args=["--no-sandbox", "--disable-dev-shm-usage"]
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
    out = sentiment(body.text[:512])[0]
    with SessionLocal() as db:
        row = Result(text=body.text, label=out["label"].lower(), score=round(out["score"], 4))
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
