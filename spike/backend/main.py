import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker
from transformers import pipeline
from playwright.async_api import async_playwright
import json
from datetime import datetime, timezone
from pathlib import Path

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
            executable_path="/usr/bin/chromium",
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()
        await page.goto(url, timeout=15000)
        await page.wait_for_load_state("domcontentloaded")

        # grab all h3 text on the page, filter out short/nav ones
        items = await page.query_selector_all("h3")
        headlines = []
        for item in items[:30]:
            text = (await item.inner_text()).strip()
            if len(text) > 20:  # filter out nav labels like "Trending Tickers"
                headlines.append(text)

        await browser.close()
    return headlines[:10]

# --- HotCopper forum scraper ---
async def scrape_hotcopper_discussions(
    ticker: str = "BHP",
    output_file: str = "scraped_hotcopper_discussions.jsonl",
    max_posts: int = 10,
) -> list[dict]:
    ticker = ticker.lower().strip()
    url = f"https://hotcopper.com.au/asx/{ticker}/discussion/"

    scraped_items = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path="/usr/bin/chromium",
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        page = await browser.new_page()
        await page.goto(url, timeout=15000)
        await page.wait_for_load_state("domcontentloaded")

        rows = await page.query_selector_all("tr")

        for row in rows:
            if len(scraped_items) >= max_posts:
                break

            text = (await row.inner_text()).strip()

            # skips empty rows / navbar-like rows
            if len(text) < 30:
                continue

            if ticker.upper() not in text.upper():
                continue

            if "Thread" not in text:
                continue

            if text.count("ASX - By Stock") > 1:
                continue

            scraped_items.append({
                "source": "HotCopper",
                "ticker": ticker.upper(),
                "url": url,
                "raw_text": text,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            })

        await browser.close()

    output_path = Path(output_file)

    with output_path.open("a", encoding="utf-8") as file:
        for item in scraped_items:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")

    return scraped_items

# --- API ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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

@app.get("/hotcopper/{ticker}")
async def hotcopper(ticker: str):
    results = await scrape_hotcopper_discussions(ticker)

    return {
        "ticker": ticker.upper(),
        "count": len(results),
        "results": results,
    }
