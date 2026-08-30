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


def _change_data_api_privileges(table: str, action: str, recipient_keyword: str) -> None:
    """Change Supabase role privileges without breaking plain PostgreSQL installs."""
    for role in ("anon", "authenticated"):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    {action} ON TABLE public."{table}" {recipient_keyword} {role};
                END IF;
            END
            $$
            """
        )


def upgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        _change_data_api_privileges(table, "REVOKE ALL PRIVILEGES", "FROM")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
        _change_data_api_privileges(
            table,
            "GRANT SELECT, INSERT, UPDATE, DELETE",
            "TO",
        )
