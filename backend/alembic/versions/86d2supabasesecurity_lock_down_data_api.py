"""lock down the Supabase Data API

Revision ID: 86d2supabasesecurity
Revises: 86d2supabaseindexes
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op


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


def upgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" '
            "FROM anon, authenticated"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public."{table}" '
            "TO anon, authenticated"
        )
