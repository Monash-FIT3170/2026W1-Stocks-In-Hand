"""Database engine, session factory, and FastAPI dependency.

This module is the runtime entry point for database access in the backend:

- ``engine`` owns the connection pool for the configured database URL.
- ``SessionLocal`` creates SQLAlchemy sessions bound to that engine.
- ``get_db`` is used by FastAPI routes through ``Depends(get_db)`` so each
  request gets a database session that is closed after the request finishes.

CRUD modules receive a ``Session`` from route handlers and use it to query,
insert, update, and delete ORM model instances.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Engine configured from app settings. For Docker test/dev runs this points to
# the Postgres service defined in the compose files.
engine = create_engine(settings.DATABASE_URL)

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
