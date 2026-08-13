"""add indexes for foreign key columns

Revision ID: 86d2supabaseindexes
Revises: 86d2cslpipeline
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "86d2supabaseindexes"
down_revision: Union[str, None] = "86d2cslpipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_watchlists_investor_id", "watchlists", ["investor_id"])
    op.create_index(
        "ix_watchlist_tickers_ticker_id",
        "watchlist_tickers",
        ["ticker_id"],
    )
    op.create_index("ix_scrape_runs_platform_id", "scrape_runs", ["platform_id"])
    op.create_index("ix_scrape_runs_ticker_id", "scrape_runs", ["ticker_id"])
    op.create_index("ix_artifacts_platform_id", "artifacts", ["platform_id"])
    op.create_index("ix_artifacts_ticker_id", "artifacts", ["ticker_id"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_ticker_id", table_name="artifacts")
    op.drop_index("ix_artifacts_platform_id", table_name="artifacts")
    op.drop_index("ix_scrape_runs_ticker_id", table_name="scrape_runs")
    op.drop_index("ix_scrape_runs_platform_id", table_name="scrape_runs")
    op.drop_index("ix_watchlist_tickers_ticker_id", table_name="watchlist_tickers")
    op.drop_index("ix_watchlists_investor_id", table_name="watchlists")
