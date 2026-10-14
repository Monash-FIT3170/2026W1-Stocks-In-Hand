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
of text for the configured LLM, and `get_discussion_posts_for_ticker` finds public discussion
about a symbol, most engaging first. Duplicate artifacts are rejected at insert time by
`content_hash`, so reads do not filter them.

`scrape_run.py`

The largest module in this folder, and the one to read first to understand the
discovery -> download -> analysis pipeline. It owns the `scrape_runs` state
machine (`enqueueing -> queued -> discovering -> downloading -> analyzing ->
completed/partial/failed`) and the per-artifact `download_status`/
`analysis_status` sub-states, called from `app/services/scrape_runs.py`
(requesting a run, for both the API and the schedule) and from every
`lambdas/*.py` worker (marking progress as a message is processed).

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
- **Terminal only when SQS gives up.** A retryable worker error calls
  `record_run_discovery_retry` / `record_artifact_download_retry` /
  `record_artifact_analysis_retry`, which store the error but keep the stage
  open. Only the receive that equals the queues' `maxReceiveCount`
  (`lambdas.common.MAX_RECEIVE_COUNT`) or a permanent error calls the
  `mark_*_failed` transition, so a run is never reported finished, or
  re-enqueued by the API or scheduler, while a message is still being retried.

Status values themselves (`ScrapeRunStatus`, `DownloadStatus`, `AnalysisStatus`)
live in `app/status.py`, not here — that module is shared by this file,
`main.py`, and every `lambdas/*.py` worker, so a status name only needs to be
spelled correctly once.

If you're adding a new pipeline stage or status, add it to `app/status.py`
first, then extend this module — don't add a parallel status field elsewhere.

`announcement.py`

Derives the ASX announcement feed and trending list from artifacts, including
the Sydney-timezone day bounds the date filters use. Each feed item is the
artifact's card (`app/services/artifact_card.py`).

`artifact_summary.py` and `artifact_sentiment.py`

Handle the generated summary and sentiment records attached to an artifact.
`artifact_summary.py` only reads summary rows: summaries are written only by
the artifact summary module (`app/services/artifact_summary.py`), which keeps
the row and the summary keys in `artifact_metadata` in step.

`watchlist.py` and `watchlist_ticker.py`

Handle investor watchlists and the join table between watchlists and tickers.

`investor.py`

Handles investors, including the password-hashing helpers used by the auth
routes.

`alert_delivery.py`

The delivery ledger behind watchlist alerts. `app/services/alert_delivery.py`
decides what each investor gets; this module records it. `claim` takes one
row per investor and artifact, or per investor and scrape run for a rollup,
and commits before any email is sent. So only one claim holder sends a row's
email at a time, and the per-run cap and daily budget counts include every
committed claim. A claim taken over once it is stale, or a provider answer
lost after the provider took the email, can still send it twice (see
`app/services/alert_delivery.py`). `record` writes the outcome and mirrors it
onto the investor's alert subscription in one transaction. The delivery
statuses live in `app/alert_vocabulary.py`.

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
