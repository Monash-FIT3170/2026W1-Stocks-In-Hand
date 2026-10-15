"""check pipeline status values

Revision ID: 86d9statuschecks
Revises: 86d9seedtickers
Create Date: 2026-10-07

The scrape run and artifact status columns are plain strings, so a typo in
a status write was stored silently. These CHECK constraints accept only the
values in ``app.status`` at this revision. A new status needs its own
migration.

The constraints are added NOT VALID: Postgres checks every row written from
now on but leaves existing rows alone, because runs written by the removed
scraping service or the admin ``POST /scrape-runs`` route may hold other
values. Once a query shows no such rows, ``VALIDATE CONSTRAINT`` can check
them too.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "86d9statuschecks"
down_revision: Union[str, None] = "86d9seedtickers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CHECKS = (
    (
        "scrape_runs",
        "ck_scrape_runs_status",
        "status",
        (
            "enqueueing",
            "queued",
            "discovering",
            "downloading",
            "analyzing",
            "running",
            "completed",
            "partial",
            "failed",
        ),
    ),
    (
        "artifacts",
        "ck_artifacts_download_status",
        "download_status",
        ("pending", "downloading", "stored", "failed"),
    ),
    (
        "artifacts",
        "ck_artifacts_analysis_status",
        "analysis_status",
        ("pending", "queued", "analyzing", "completed", "failed", "skipped"),
    ),
)


def upgrade() -> None:
    for table, name, column, values in CHECKS:
        allowed = ", ".join(f"'{value}'" for value in values)
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"CHECK ({column} IN ({allowed})) NOT VALID"
        )


def downgrade() -> None:
    for table, name, _column, _values in CHECKS:
        op.drop_constraint(name, table, type_="check")
