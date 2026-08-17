# CRUD Implementation

The `crud` folder contains database access functions.

CRUD means:

- Create
- Read
- Update
- Delete

These functions sit between API routes and SQLAlchemy models.

## Responsibility

CRUD modules should:

- receive a SQLAlchemy `Session`;
- query model objects;
- create model objects;
- update model fields;
- delete model objects;
- commit database changes when writes should be saved.

CRUD modules should not:

- know about HTTP status codes;
- raise FastAPI `HTTPException` for normal not-found cases;
- parse request bodies directly;
- define route paths.

Those responsibilities belong in the route layer.

## Common Flow

Most requests follow this path:

1. A route receives an HTTP request.
2. FastAPI gives the route a database session through `Depends(get_db)`.
3. The route calls a CRUD function.
4. The CRUD function queries or writes SQLAlchemy models.
5. The route converts the result into an HTTP response.

Example:

```python
@router.get("/{ticker_id}")
def get_ticker(ticker_id: UUID, db: Session = Depends(get_db)):
    ticker = crud.get_ticker(db, ticker_id=ticker_id)
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker
```

## File Pattern

Each CRUD file usually matches a model and route file:

- `models/ticker.py`
- `schemas/ticker.py`
- `crud/ticker.py`
- `api/routes/ticker.py`

This keeps each resource easy to find.

## Important CRUD Modules

`artifact.py`

Handles artifact lookups and the text-assembly helpers the analysis routes use.
`build_recent_artifact_chunk` concatenates recent artifacts into a single block
of text for Groq, and `get_reddit_posts_for_ticker` finds Reddit posts
mentioning a symbol. Duplicate artifacts are rejected at insert time by
`content_hash`, so reads do not filter them.

`scrape_run.py`

The largest module in this folder, and the one to read first to understand the
discovery -> download -> analysis pipeline. It owns the `scrape_runs` state
machine (`enqueueing -> queued -> discovering -> downloading -> analyzing ->
completed/partial/failed`) and the per-artifact `download_status`/
`analysis_status` sub-states, called from `main.py` (enqueueing a run) and from
every `lambdas/*.py` worker (marking progress as a message is processed).

Two properties make it safe under SQS's at-least-once delivery:

- **Idempotent creation.** `get_or_create_queued_run` and `get_or_create_artifact`
  both handle the `IntegrityError` race on a unique constraint
  (`idempotency_key`, `source_document_identity`) by re-querying instead of
  failing, so a duplicate message reuses the existing row rather than creating
  a second one.
- **Monotonic status transitions.** Row-level locking (`_lock_run`/
  `_lock_artifact` via `with_for_update()`) plus the `RUN_DOWNSTREAM_OF_DISCOVERY`
  check (from `app.status`) stop an out-of-order retry from moving a run's
  status *backwards* once a later stage has already advanced it.

Status values themselves (`ScrapeRunStatus`, `DownloadStatus`, `AnalysisStatus`)
live in `app/status.py`, not here — that module is shared by this file,
`main.py`, and every `lambdas/*.py` worker, so a status name only needs to be
spelled correctly once.

If you're adding a new pipeline stage or status, add it to `app/status.py`
first, then extend this module — don't add a parallel status field elsewhere.

`announcement.py`

Derives the ASX announcement feed and trending list from artifacts, including
the Sydney-timezone day bounds the date filters use.

`artifact_summary.py` and `artifact_sentiment.py`

Handle the generated summary and sentiment records attached to an artifact.

`watchlist.py` and `watchlist_ticker.py`

Handle investor watchlists and the join table between watchlists and tickers.

`investor.py`

Handles investors, including the password-hashing helpers used by the auth
routes.

## Write Behavior

Create/update/delete functions usually call:

```python
db.commit()
db.refresh(model)
```

`commit()` persists the write to the database.

`refresh()` reloads generated values such as IDs and database defaults.

## Error Handling Pattern

CRUD functions generally return `None` when a row does not exist.

Routes are responsible for converting that into an HTTP error:

```python
item = crud.get_item(db, item_id=item_id)
if not item:
    raise HTTPException(status_code=404, detail="Item not found")
```

This keeps CRUD reusable outside HTTP routes, such as in scripts or tests.
