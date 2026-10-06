"""FastAPI application and the Queue A scrape producer."""

from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_investor,
    require_admin_for_writes,
    require_admin_investor,
)
from app.api.routes import (
    announcement,
    artifact,
    artifact_sentiment,
    artifact_summary,
    auth,
    blog,
    bluesky,
    category_sentiment,
    gemini,
    information_platform,
    investor,
    mastodon,
    news,
    notification_preferences,
    public_discussion,
    reddit,
    scrape_run,
    ticker,
    watchlist,
    watchlist_ticker,
)
from app.core.config import settings
from app.crud import scrape_run as scrape_run_crud
from app.database.connection import get_db
from app.messages import QueueAMessage
from app.models.investor import Investor
from app.schemas.scrape_run import ScrapeEnqueueResponse
from app.services import scrape_queue
from app.sources import source_for_ticker
from app.status import RUN_ACTIVE_OR_FINISHED, ScrapeRunStatus

app = FastAPI(title="StonksInHand API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Keep the API deployment small. Heavy scraping and analysis dependencies are
# imported only by their worker or request path.
#
# Who may call a route is set here, once per router, so a route added to a
# router gets its router's policy without remembering a dependency:
# - public read: reads are open unless the route asks for a login, and every
#   other method needs an admin;
# - investor: every route needs a signed-in investor (their own data);
# - admin: every route needs an admin (accounts and cost-bearing jobs);
# - self-managed: routes that establish an identity or act on a signed token
#   choose for themselves. test_access_policy.py holds their public routes
#   to an allowlist.
PUBLIC_READ_ROUTERS = (
    ticker,
    artifact,
    artifact_summary,
    artifact_sentiment,
    scrape_run,
    information_platform,
    reddit,
    public_discussion,
    category_sentiment,
    announcement,
)
INVESTOR_ROUTERS = (watchlist, watchlist_ticker)
ADMIN_ROUTERS = (investor, news, blog, bluesky, mastodon, gemini)
SELF_MANAGED_ROUTERS = (auth, notification_preferences)

for route_module in PUBLIC_READ_ROUTERS:
    app.include_router(route_module.router, dependencies=[Depends(require_admin_for_writes)])
for route_module in INVESTOR_ROUTERS:
    app.include_router(route_module.router, dependencies=[Depends(get_current_investor)])
for route_module in ADMIN_ROUTERS:
    app.include_router(route_module.router, dependencies=[Depends(require_admin_investor)])
for route_module in SELF_MANAGED_ROUTERS:
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
def health(db: Session = Depends(get_db)) -> dict:
    """Return whether the API process can reach its database."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": "database unreachable"},
        )
    return {"status": "ok"}


@app.get("/ready")
def readiness(db: Session = Depends(get_db)) -> dict:
    """Verify that the API can query the schema required by deployed routes."""
    try:
        db.execute(text("SELECT is_duplicate FROM artifacts LIMIT 0"))
        db.execute(text("SELECT prompt_version FROM artifact_summaries LIMIT 0"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database schema is not ready",
        ) from exc
    return {
        "status": "ready",
        "checks": {"database": "ok", "artifact_schema": "ok"},
    }


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
def analyse(
    body: AnalyseRequest,
    _admin: Investor = Depends(require_admin_investor),
) -> dict:
    """Keep local FinBERT available without loading it at API startup."""
    try:
        from app.services import sentiment as sentiment_service

        output = sentiment_service.analyse_text(body.text)
    except (ImportError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="FinBERT sentiment runs in the document analysis worker",
        ) from exc
    return {
        "label": output["sentiment_label"],
        "score": output["score"],
    }


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
    run, created = scrape_run_crud.get_or_create_queued_run(
        db,
        ticker=symbol,
        source_url=source_url,
        idempotency_key=f"scrape:{symbol}:{request_key}",
    )

    if not created and run.status in RUN_ACTIVE_OR_FINISHED:
        return {
            "status": run.status,
            "ticker": symbol,
            "scrape_run_id": run.id,
        }

    if not created and run.status == ScrapeRunStatus.FAILED:
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
        "status": ScrapeRunStatus.QUEUED,
        "ticker": symbol,
        "scrape_run_id": run.id,
    }

@app.get("/tickers")
def tickers(skip: int = 0, limit: int = 100, db=Depends(get_db)):
    return ticker.get_tickers(skip=skip, limit=limit, db=db)
