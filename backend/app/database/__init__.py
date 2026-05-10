"""Database package exports.

Importing from ``app.database`` gives other modules access to:
- ``Base``: the shared SQLAlchemy model base and metadata registry.
- ``engine``: the configured SQLAlchemy database engine.
- ``SessionLocal``: the session factory used by API requests and scripts.
"""

from .base import Base
from .connection import SessionLocal, engine
