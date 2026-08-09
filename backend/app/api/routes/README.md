# Routes Implementation

The `api/routes` folder contains FastAPI route modules.

Each route module defines HTTP endpoints for one backend resource, such as
tickers, artifacts, announcements, or watchlists.

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
router = APIRouter(prefix="/artifacts", tags=["artifacts"])
```

That means every route in the file starts with `/artifacts`.

Examples:

- `artifact.py` uses `/artifacts`.
- `watchlist.py` uses `/watchlists`.
- `watchlist_ticker.py` uses `/watchlist-tickers`.
- `artifact_sentiment.py` uses `/artifact-sentiments`.

## How Routes Are Registered

The routers are imported and registered in `backend/main.py`:

```python
app.include_router(artifact.router)
app.include_router(watchlist.router)
```

If a route module is not included in `main.py`, its endpoints will not be
available in the running API.

## Main Route Groups

Investor and watchlist routes:

- `investor.py`: create, read, update, and delete investors.
- `auth.py`: sign up, sign in, sign out, and current-identity lookup.
- `watchlist.py`: create, read, update, and delete watchlists.
- `watchlist_ticker.py`: add/list/remove tickers in a watchlist.

Ticker routes:

- `ticker.py`: create, list, fetch, and update tickers, plus the brief
  endpoints the frontend reads (`/overview`, `/brief-aside`, `/news-feed`,
  `/deep-dive-timeline`). Prices are fetched live from Yahoo here rather than
  stored, so there is no market data route.

Source content routes:

- `information_platform.py`: manage source platforms.
- `artifact.py`: create and fetch artifacts.
- `artifact_summary.py`: create and fetch summaries.
- `artifact_sentiment.py`: create and fetch sentiment records.
- `announcement.py`: the ASX announcement feed and trending list, derived from
  artifacts.

Analysis routes:

- `category_sentiment.py`: the `/sentiment/{ticker}` pipeline.
- `reddit.py`: Reddit scraping and per-ticker Reddit summaries.
- `gemini.py`: Groq-backed summarisation and categorisation.

Operational routes:

- `scrape_run.py`: create and fetch scrape run records.

## Where Validation Happens

Request and response shapes come from `app/schemas`.

For example, `artifact.py` uses:

- `ArtifactCreate` for incoming artifact creation data;
- `ArtifactResponse` for outgoing artifact data.

FastAPI uses those schemas to validate input and serialize output.
