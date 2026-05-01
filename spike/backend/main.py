import os
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from transformers import pipeline
from playwright.async_api import async_playwright
from pathlib import Path

from scrapers.registry import scrape, available_tickers

# --- DB ---
engine = create_engine(os.environ["DATABASE_URL"])
Session = sessionmaker(bind=engine)
Base = declarative_base()

class Result(Base):
    __tablename__ = "results"
    id    = Column(Integer, primary_key=True)
    text  = Column(String)
    label = Column(String)
    score = Column(Float)

Base.metadata.create_all(engine)

# --- HuggingFace: FinBERT ---
sentiment = pipeline("text-classification", model="ProsusAI/finbert")

# --- Playwright scraper ---
async def scrape_yahoo_headlines(ticker: str = "BHP.AX") -> list[str]:
    url = f"https://finance.yahoo.com/quote/{ticker}/news/"
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()
        await page.goto(url, timeout=15000)
        await page.wait_for_load_state("domcontentloaded")

        items = await page.query_selector_all("h3")
        headlines = []
        for item in items[:30]:
            text = (await item.inner_text()).strip()
            if len(text) > 20:
                headlines.append(text)

        await browser.close()
    return headlines[:10]

# --- API ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

OUTPUT_DIR = Path("/app/output")

class AnalyseRequest(BaseModel):
    text: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyse")
def analyse(body: AnalyseRequest):
    out = sentiment(body.text[:512])[0]
    with Session() as db:
        row = Result(text=body.text, label=out["label"].lower(), score=round(out["score"], 4))
        db.add(row)
        db.commit()
        db.refresh(row)
    return {"id": row.id, "label": row.label, "score": row.score}

@app.get("/results")
def results():
    with Session() as db:
        rows = db.query(Result).order_by(Result.id.desc()).limit(10).all()
    return [{"id": r.id, "text": r.text[:80], "label": r.label, "score": r.score} for r in rows]

@app.get("/headlines")
async def headlines():
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