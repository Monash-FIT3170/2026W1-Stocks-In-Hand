"""lock down the Supabase Data API

Revision ID: 86d2supabasesecurity
Revises: 86d2supabaseindexes
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "86d2supabasesecurity"
down_revision: Union[str, None] = "86d2supabaseindexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "investors",
    "auth_sessions",
    "tickers",
    "watchlists",
    "watchlist_tickers",
    "information_platforms",
    "scrape_runs",
    "artifacts",
    "artifact_sentiments",
    "artifact_summaries",
    "alembic_version",
)

# Supabase creates these Data API roles automatically; a plain local/test
# Postgres instance (docker-compose-tests.yml, local dev) does not. Row
# level security is still enabled/disabled either way -- only the
# REVOKE/GRANT against these specific roles is conditional, so behaviour
# against a real Supabase database is unchanged.
DATA_API_ROLES = ("anon", "authenticated")


def _existing_roles(names: Sequence[str]) -> list[str]:
    bind = op.get_bind()
    rows = bind.execute(
        text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"),
        {"names": list(names)},
    )
    return sorted(row[0] for row in rows)


def upgrade() -> None:
    roles = _existing_roles(DATA_API_ROLES)
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        if roles:
            op.execute(
                f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" '
                f"FROM {', '.join(roles)}"
            )


def downgrade() -> None:
    roles = _existing_roles(DATA_API_ROLES)
    for table in reversed(TABLES):
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
        if roles:
            op.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public."{table}" '
                f"TO {', '.join(roles)}"
            )
