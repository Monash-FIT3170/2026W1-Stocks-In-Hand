"""Keep alert delivery ledger rows attached to their scrape runs.

Revision ID: 86d4k9m2q
Revises: 86d4k9m2p
Create Date: 2026-08-26
"""

# Alembic requires lower-case revision metadata and exposes ``op`` at runtime.
# pylint: disable=invalid-name,no-name-in-module

from typing import Sequence, Union

from alembic import op


revision: str = "86d4k9m2q"
down_revision: Union[str, None] = "86d4k9m2p"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "alert_deliveries_scrape_run_id_fkey"


def upgrade() -> None:
    """Prevent a scrape-run delete from invalidating rollup ledger rows."""
    op.drop_constraint(
        CONSTRAINT_NAME,
        "alert_deliveries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        CONSTRAINT_NAME,
        "alert_deliveries",
        "scrape_runs",
        ["scrape_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Restore the original nullable scrape-run foreign key action."""
    op.drop_constraint(
        CONSTRAINT_NAME,
        "alert_deliveries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        CONSTRAINT_NAME,
        "alert_deliveries",
        "scrape_runs",
        ["scrape_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
