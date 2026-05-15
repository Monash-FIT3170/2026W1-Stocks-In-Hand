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

Investor and watchlist models:

- `investor.py`: users/investors tracked by the app.
- `watchlist.py`: a named watchlist owned by an investor.
- `watchlist_ticker.py`: join table linking watchlists to tickers.

Ticker and market models:

- `ticker.py`: listed companies or stock symbols.
- `market_data.py`: historical price/volume data for a ticker.

Source content models:

- `information_platform.py`: source platforms such as news sites or forums.
- `artifact.py`: scraped or stored source content.
- `artifact_chunk.py`: text chunks derived from artifacts.
- `artifact_summary.py`: generated summaries for artifacts.
- `artifact_sentiment.py`: sentiment/stance analysis for artifacts.
- `artifact_topic.py`: join table linking artifacts to topics.
- `topic.py`: tracked topics or themes.

Claim and report models:

- `claim.py`: extracted/generated claim about a ticker.
- `claim_source.py`: evidence connecting a claim to an artifact or chunk.
- `report.py`: generated report for a ticker.
- `report_claim.py`: join table linking reports to claims.

Operational models:

- `alert.py`: investor-facing alerts.
- `scrape_run.py`: scrape job execution records.
- `llm_run.py`: LLM task execution records.
- `extracted_fact.py`: facts extracted from artifacts/chunks.
- `result.py`: simple sentiment result table used by the legacy `/analyse`
  and `/results` endpoints.
- `user.py`: simple user table used by the separate user route.

## Important Relationship Flow

The report evidence path is:

`Report -> ReportClaim -> Claim -> ClaimSource -> Artifact`

This means:

1. A `Report` belongs to a ticker.
2. A `Claim` also belongs to a ticker.
3. `ReportClaim` links a report to one or more claims.
4. `ClaimSource` links each claim to supporting evidence.
5. `Artifact` stores the original source content for that evidence.

The report CRUD code depends on these ORM relationships to load a report with
its related claims and evidence.

## Foreign Keys Vs Relationships

Foreign keys define database-level links:

```python
ticker_id = Column(UUID(as_uuid=True), ForeignKey("tickers.id"))
```

Relationships define Python-level navigation:

```python
report_claims = relationship("ReportClaim", back_populates="report")
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
