"""Shared SQLAlchemy declarative base.

Every ORM model in ``app.models`` inherits from ``Base``. SQLAlchemy uses this
single base object to collect table metadata, including table names, columns,
primary keys, foreign keys, indexes, and relationship mappings.

Alembic also reads ``Base.metadata`` in ``alembic/env.py`` when generating or
running migrations. That means new database models must inherit from this
object if they should become part of the application schema.
"""

from sqlalchemy.orm import declarative_base

# Central metadata registry for all SQLAlchemy model classes.
Base = declarative_base()
