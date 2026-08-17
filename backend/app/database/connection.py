"""Database engine, session factory, and FastAPI dependency.

This module is the runtime entry point for database access in the backend:

- ``engine`` owns the connection pool for the configured database URL.
- ``SessionLocal`` creates SQLAlchemy sessions bound to that engine.
- ``get_db`` is used by FastAPI routes through ``Depends(get_db)`` so each
  request gets a database session that is closed after the request finishes.

CRUD modules receive a ``Session`` from route handlers and use it to query,
insert, update, and delete ORM model instances.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Engine configured from app settings. For Docker test/dev runs this points to
# the Postgres service defined in the compose files.
_engine_options = {"pool_pre_ping": True}
if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    # Lambda execution environments already scale horizontally. Avoid retaining
    # one SQLAlchemy pool per warm environment when using Supabase's pooler.
    _engine_options["poolclass"] = NullPool
elif "pooler.supabase.com" in settings.DATABASE_URL:
    # Supabase Session Pooler has a per-project client-connection cap. Cap
    # SQLAlchemy's own pool below the Supabase limit and recycle connections
    # so idle ones don't get killed by the pooler.
    _engine_options.update(pool_size=5, max_overflow=5, pool_recycle=1800)

engine = create_engine(settings.DATABASE_URL, **_engine_options)

# Session factory used by API routes. ``autocommit=False`` means CRUD functions
# must explicitly call ``commit()`` when they want writes persisted.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Yield one database session for a FastAPI request.

    FastAPI treats this generator as a dependency. Code before ``yield`` runs
    before the route handler, and code after ``yield`` runs after the response
    path finishes. The ``finally`` block guarantees the session is closed even
    if a route raises an exception.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
