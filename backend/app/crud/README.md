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

`report.py`

Handles report lookups and report-level calculations. The `get_report`
function loads a report together with its report claims, claims, claim sources,
and source artifacts.

`report_claim.py`

Handles the join table between reports and claims. It can create, fetch, list,
and delete report-claim links.

`claim.py`

Handles claims. Claims are tied to tickers. Claims are connected to source
artifacts through `claim_sources`, not through a direct `artifact_id` column.

`claim_source.py`

Handles evidence records that connect claims to artifacts and optional artifact
chunks.

`watchlist.py` and `watchlist_ticker.py`

Handle investor watchlists and the join table between watchlists and tickers.

`llm_run.py`

Handles stored LLM execution records. Current records are grouped by task type,
model, status, token counts, and cost fields.

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
