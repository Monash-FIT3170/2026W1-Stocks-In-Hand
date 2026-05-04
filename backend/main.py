"""
main python file which creates database connection, connects to finBERT, and runs a FastAPI server
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from transformers import pipeline
from playwright.async_api import async_playwright

# --- DB ---
engine = create_engine(os.environ["DATABASE_URL"])
SESSION = sessionmaker(bind=engine)

class Base(DeclarativeBase):
    """Class needed by ORM as a base class"""
    pass        # pylint: disable=unnecessary-pass

class Result(Base):
    """Database table representing a sentiment analysis result"""
    __tablename__ = "results"
    id    = Column(Integer, primary_key=True)
    text  = Column(String)
    label = Column(String)
    score = Column(Float)

Base.metadata.create_all(engine)

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
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class AnalyseRequest(BaseModel):
    """Class representing the structure of requests made to the analyse API"""
    text: str

@app.get("/health")
def health() -> dict:
    """Returns the health status of the server"""
    return {"status": "ok"}

@app.post("/analyse")
def analyse(body: AnalyseRequest) -> dict:
    """Analyses the sentiment of a headline passed in as an AnalyseRequest"""
    out = sentiment(body.text[:512])[0]
    with SESSION() as db:
        row = Result(text=body.text, label=out["label"].lower(), score=round(out["score"], 4))
        db.add(row)
        db.commit()
        db.refresh(row)
    return {"id": row.id, "label": row.label, "score": row.score}

@app.get("/results")
def results() -> list[dict]:
    """Returns a list of sentiment analysis results"""
    with SESSION() as db:
        rows = db.query(Result).order_by(Result.id.desc()).limit(10).all()
    return [{"id": r.id, "text": r.text[:80], "label": r.label, "score": r.score} for r in rows]

@app.get("/headlines")
async def headlines() -> list[str]:
    """Returns a list of headlines from Yahoo for the default ticker"""
    return await scrape_yahoo_headlines()
