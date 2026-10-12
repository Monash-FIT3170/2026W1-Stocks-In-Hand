# Models Implementation

The `models` folder contains the SQLAlchemy ORM classes that define the
backend database schema.

Each model class maps to one database table.

## What A Model Does

A model usually defines:

- the table name with `__tablename__`;
- columns and their SQL types;
- primary keys;
- foreign keys;
- uniqueness rules;
- relationships to other models.

Example shape:

```python
class Ticker(Base):
    __tablename__ = "tickers"

    id = Column(UUID(as_uuid=True), primary_key=True)
    symbol = Column(String, unique=True, nullable=False)
```

Every model inherits from `app.database.base.Base`. That is how SQLAlchemy and
Alembic discover the database schema.

## Main Groups

The schema is deliberately small: ten tables, listed below. Prices are read live
from Yahoo in `api/routes/ticker.py` rather than stored, so there is no market
data table.

Investor and watchlist models:

- `investor.py`: users/investors tracked by the app.
- `auth_session.py`: login sessions backing the session cookie.
- `watchlist.py`: a named watchlist owned by an investor.
- `watchlist_ticker.py`: join table linking watchlists to tickers.

Ticker models:

- `ticker.py`: listed companies or stock symbols.

Source content models:

- `information_platform.py`: source platforms such as news sites or forums.
- `artifact.py`: scraped or stored source content.
- `artifact_summary.py`: generated summaries for artifacts.
- `artifact_sentiment.py`: sentiment/stance analysis for artifacts.

Operational models:

- `scrape_run.py`: scrape job execution records.

## Important Relationship Flow

The analysis path is:

`Ticker -> Artifact -> ArtifactSummary / ArtifactSentiment`

This means:

1. An `Artifact` belongs to a ticker and to the platform it came from.
2. `crud.artifact.store_artifact_analysis` (called from `lambdas/analysis.py`) writes
   the artifact, then its summary and sentiment.
3. The ticker overview, news feed, and deep-dive endpoints read them back
   through the `summaries` and `sentiments` backrefs.

Duplicate artifacts are rejected at insert time by `content_hash`, so there is
no duplicate flag to filter on when reading.

## Foreign Keys Vs Relationships

Foreign keys define database-level links:

```python
ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"))
```

Relationships define Python-level navigation:

```python
ticker = relationship("Ticker", backref="artifacts")
```

Both matter:

- foreign keys protect database integrity;
- relationships let CRUD code move between related model objects.

## When Adding A New Model

When adding a new database table:

1. Create a model file in this folder.
2. Inherit from `Base`.
3. Add the model import to `models/__init__.py`.
4. Generate an Alembic migration.
5. Add tests if the model affects important database behavior.
