"""FastAPI application and the Queue A scrape producer."""

from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes import (
    alert,
    announcement,
    artifact,
    artifact_chunk,
    artifact_sentiment,
    artifact_summary,
    artifact_topic,
    auth,
    claim,
    claim_source,
    category_sentiment,
    extracted_fact,
    gemini,
    information_platform,
    investor,
    llm_run,
    market_data,
    reddit,
    report,
    report_claim,
    scrape_run,
    ticker,
    topic,
    watchlist,
    watchlist_ticker,
)
from app.core.config import settings
from app.api.deps import require_admin_investor
from app.crud import scrape_run as scrape_run_crud
from app.database.connection import SessionLocal, get_db
from app.messages import QueueAMessage
from app.models.result import Result
from app.models.investor import Investor
from app.schemas.scrape_run import ScrapeEnqueueResponse
from app.services import scrape_queue
from app.sources import source_for_ticker


app = FastAPI(title="StonksInHand API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database-backed routes stay in the small API deployment. The sentiment
# service lazily imports FinBERT only when inference is requested.
for route_module in (
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
    category_sentiment,
    report_claim,
    llm_run,
    scrape_run,
    market_data,
    information_platform,
    topic,
    auth,
    reddit,
    gemini,
    announcement,
):
    app.include_router(route_module.router)


@app.get("/")
def root():
    return {
        "message": "StonksInHand FastAPI backend",
        "docs": "/docs",
        "health": "/health",
        "endpoints": [
            "/scrape/{ticker_symbol}",
            "/scrape-runs/{scrape_run_id}",
            "/tickers",
            "/auth/sign-in",
        ],
    }


@app.get("/health")
def health() -> dict:
    """Return the health status of the API process."""
    return {"status": "ok"}


@app.get("/viewer", response_class=HTMLResponse)
def viewer():
    return (Path(__file__).parent / "viewer.html").read_text(encoding="utf-8")


async def scrape_yahoo_headlines(ticker_symbol: str = "BHP.AX") -> list[str]:
    """Run the legacy local Yahoo headline scraper on demand."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="The local Playwright headline scraper is not deployed in the API Lambda",
        ) from exc

    url = f"https://finance.yahoo.com/quote/{ticker_symbol}/news/"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--headless=new",
            ],
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


class AnalyseRequest(BaseModel):
    text: str


@app.post("/analyse")
def analyse(body: AnalyseRequest) -> dict:
    """Keep the legacy local sentiment endpoint without loading FinBERT at boot."""
    try:
        from app.services import sentiment as sentiment_service
        out = sentiment_service.analyse_text(body.text)
    except (ImportError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="FinBERT sentiment runs in the document analysis worker",
        ) from exc

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
    with SessionLocal() as db:
        rows = db.query(Result).order_by(Result.id.desc()).limit(10).all()
    return [
        {
            "id": row.id,
            "text": row.text[:80],
            "label": row.label,
            "score": row.score,
        }
        for row in rows
    ]


@app.get("/headlines")
async def headlines() -> list[str]:
    return await scrape_yahoo_headlines()


@app.post(
    "/scrape/{ticker_symbol}",
    response_model=ScrapeEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def scrape_ticker(
    ticker_symbol: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    _admin: Investor = Depends(require_admin_investor),
):
    """Create durable run state and enqueue website discovery."""
    symbol = ticker_symbol.strip().upper()
    source = source_for_ticker(symbol)
    if source is None or symbol not in settings.SUPPORTED_TICKERS:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{symbol}' is not enabled for scraping. "
                f"Enabled: {settings.SUPPORTED_TICKERS}"
            ),
        )
    source_url = settings.SOURCE_URLS.get(symbol, source.source_url)
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise HTTPException(status_code=400, detail="Idempotency-Key is empty")
        if len(idempotency_key) > 128:
            raise HTTPException(status_code=400, detail="Idempotency-Key is too long")

    request_key = idempotency_key or uuid4().hex
    durable_key = f"scrape:{symbol}:{request_key}"
    run, created = scrape_run_crud.get_or_create_queued_run(
        db,
        ticker=symbol,
        source_url=source_url,
        idempotency_key=durable_key,
    )

    active_or_finished = {
        "queued",
        "discovering",
        "downloading",
        "analyzing",
        "partial",
        "completed",
    }
    if not created and run.status in active_or_finished:
        return {
            "status": run.status,
            "ticker": symbol,
            "scrape_run_id": run.id,
        }

    if not created and run.status == "failed":
        run = scrape_run_crud.mark_run_enqueueing(db, run.id)

    message = QueueAMessage(
        scrape_run_id=run.id,
        ticker=symbol,
        source_url=source_url,
        source_adapter=source.adapter,
    )
    try:
        scrape_queue.enqueue_discovery(message)
    except Exception as exc:
        scrape_run_crud.mark_run_discovery_failed(
            db,
            run.id,
            error="Could not enqueue website discovery",
        )
        raise HTTPException(
            status_code=503,
            detail="Could not enqueue website discovery",
        ) from exc

    scrape_run_crud.mark_run_queued_if_enqueueing(db, run.id)

    return {
        "status": "queued",
        "ticker": symbol,
        "scrape_run_id": run.id,
    }


@app.get("/tickers")
def tickers(skip: int = 0, limit: int = 100, db=Depends(get_db)):
    return ticker.get_tickers(skip=skip, limit=limit, db=db)
