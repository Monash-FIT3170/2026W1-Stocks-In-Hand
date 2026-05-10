# Routes Implementation

The `api/routes` folder contains FastAPI route modules.

Each route module defines HTTP endpoints for one backend resource, such as
tickers, reports, claims, artifacts, or watchlists.

## Responsibility

Route modules should:

- define URL paths and HTTP methods;
- receive request data;
- get a database session with `Depends(get_db)`;
- call CRUD functions;
- raise `HTTPException` for HTTP-specific errors;
- return response objects that match the Pydantic response schemas.

Route modules should not:

- contain complex database queries;
- directly manage database transactions unless there is a specific reason;
- define SQLAlchemy models;
- duplicate business logic already handled by CRUD functions.

## Common Route Flow

Most route handlers follow this pattern:

```python
@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: UUID, db: Session = Depends(get_db)):
    item = crud.get_item(db, item_id=item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item
```

The pieces are:

- `@router.get(...)`: exposes an HTTP endpoint.
- `response_model=...`: tells FastAPI how to serialize the response.
- `db: Session = Depends(get_db)`: creates one database session for the
  request.
- `crud.get_item(...)`: delegates database work to the CRUD layer.
- `HTTPException`: converts application conditions into HTTP responses.

## Router Prefixes

Each file creates an `APIRouter` with a prefix:

```python
router = APIRouter(prefix="/reports", tags=["reports"])
```

That means every route in the file starts with `/reports`.

Examples:

- `report.py` uses `/reports`.
- `claim.py` uses `/claims`.
- `artifact.py` uses `/artifacts`.
- `watchlist.py` uses `/watchlists`.
- `report_claim.py` uses `/report-claims`.

## How Routes Are Registered

The routers are imported and registered in `backend/main.py`:

```python
app.include_router(report.router)
app.include_router(claim.router)
```

If a route module is not included in `main.py`, its endpoints will not be
available in the running API.

## Main Route Groups

Investor and watchlist routes:

- `investor.py`: create, read, update, and delete investors.
- `watchlist.py`: create, read, update, and delete watchlists.
- `watchlist_ticker.py`: add/list/remove tickers in a watchlist.

Ticker and market routes:

- `ticker.py`: create, list, fetch, and update tickers.
- `market_data.py`: create and fetch market data by ticker.

Source content routes:

- `information_platform.py`: manage source platforms.
- `artifact.py`: create and fetch artifacts.
- `artifact_chunk.py`: create and fetch artifact chunks.
- `artifact_summary.py`: create and fetch summaries.
- `artifact_sentiment.py`: create and fetch sentiment records.
- `artifact_topic.py`: link artifacts to topics.
- `topic.py`: create and fetch topics.

Claim and report routes:

- `claim.py`: create and fetch claims.
- `claim_source.py`: create and fetch claim evidence.
- `report.py`: create and fetch reports and report sentiment.
- `report_claim.py`: link reports to claims.

Operational routes:

- `alert.py`: create, fetch, update, and delete alerts.
- `scrape_run.py`: create and fetch scrape run records.
- `llm_run.py`: create and fetch LLM run records.

## Where Validation Happens

Request and response shapes come from `app/schemas`.

For example, `report.py` uses:

- `ReportCreate` for incoming report creation data;
- `ReportResponse` for outgoing report data.

FastAPI uses those schemas to validate input and serialize output.
