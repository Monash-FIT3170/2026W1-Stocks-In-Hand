# Database Implementation

This folder contains the shared database setup used by the backend.

## Main Pieces

`base.py`

Defines `Base`, the shared SQLAlchemy declarative base. Every model in
`app/models` inherits from this object. SQLAlchemy stores table metadata on
`Base.metadata`, and Alembic uses that metadata when working with migrations.

`connection.py`

Creates the database engine and session factory:

- `engine` connects SQLAlchemy to the database configured by `DATABASE_URL`.
- `SessionLocal` creates database sessions bound to that engine.
- `get_db()` is the FastAPI dependency used by route handlers.

`__init__.py`

Re-exports the database objects that other modules commonly import.

## Request Flow

Most API endpoints follow this path:

1. A route function declares `db: Session = Depends(get_db)`.
2. FastAPI calls `get_db()` and gives the route a database session.
3. The route passes that session into a CRUD function.
4. The CRUD function queries or writes SQLAlchemy model objects.
5. When the request is finished, `get_db()` closes the session.

## Model And Migration Flow

The database schema is defined by the ORM models in `app/models`.

Each model:

- inherits from `Base`;
- declares a `__tablename__`;
- defines columns and foreign keys;
- may define relationships to other models.

Alembic reads `Base.metadata` in `alembic/env.py`. When migrations are run,
Alembic applies the schema changes to Postgres.

## Important Tables

The report evidence flow uses these core tables:

- `tickers`: listed companies or symbols being tracked.
- `reports`: generated reports for a ticker.
- `claims`: extracted or generated claims about a ticker.
- `report_claims`: join table linking reports to claims.
- `claim_sources`: evidence linking claims to source artifacts.
- `artifacts`: scraped or stored source content.

The ORM relationship chain for report evidence is:

`Report -> ReportClaim -> Claim -> ClaimSource -> Artifact`

That relationship is used by report CRUD code when loading a report with its
supporting claims and evidence.

## Configuration

The database URL comes from `app/core/config.py`.

The environment variable is:

`DATABASE_URL`

If it is not set, the backend defaults to:

`postgresql://user:password@localhost:5432/spike`

Docker compose files provide their own `DATABASE_URL` so containers connect to
the Postgres service rather than localhost.
