"""Reproduce the deployed database's schema drift, then upgrade it to head.

Staging's database was created from older forms of the baseline migration.
It has Supabase's ``anon`` and ``authenticated`` roles, and it is missing
``artifacts.is_duplicate`` and ``artifact_summaries.prompt_version``, which
``86d2artifactduplicate`` and ``86d8promptversion`` add back. CI runs this
against an empty Postgres to prove an upgrade from that state reaches head:

    python -m scripts.reproduce_deployed_schema_drift   # from backend/

It creates cluster-wide roles and drops columns, so never point it at a
database or server you want to keep.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import settings

BACKEND = Path(__file__).resolve().parents[1]
# The last revision before the migrations that repair the drift.
DRIFTED_REVISION = "86d2cognitoidentity"


def main() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    engine = create_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE ROLE anon NOLOGIN"))
            connection.execute(text("CREATE ROLE authenticated NOLOGIN"))
        command.upgrade(config, DRIFTED_REVISION)
        with engine.connect() as connection:
            connection.execute(text("ALTER TABLE artifacts DROP COLUMN is_duplicate"))
            connection.execute(
                text("ALTER TABLE artifact_summaries DROP COLUMN prompt_version")
            )
        command.upgrade(config, "head")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
