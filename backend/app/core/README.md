# Core Implementation

The `core` folder contains backend-wide configuration and shared application
settings.

## Files

`config.py`

Defines the `Settings` class and creates the shared `settings` object.

The most important setting currently is:

`DATABASE_URL`

This value tells SQLAlchemy and Alembic which database to connect to.

## How Configuration Works

The backend reads configuration from environment variables first:

```python
os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/spike")
```

That means:

1. If `DATABASE_URL` is set in the environment, the backend uses it.
2. If it is not set, the backend falls back to the local Postgres URL.

Docker compose files set `DATABASE_URL` for container runs, so the backend
connects to the Postgres service inside Docker instead of trying to use
`localhost`.

## Where It Is Used

`settings.DATABASE_URL` is used by:

- `app/database/connection.py` to create the SQLAlchemy engine.
- `alembic/env.py` to run database migrations against the correct database.

## When To Add More Settings

Add new values here when they are application-level configuration, such as:

- database URLs;
- API keys;
- model names;
- allowed frontend origins;
- environment-specific feature flags.

Avoid hard-coding those values directly in route, CRUD, or model files.
