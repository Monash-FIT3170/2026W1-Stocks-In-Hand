"""repair artifact summary prompt-version column drift

Revision ID: 86d8promptversion
Revises: 86d7m4q2xpublic
Create Date: 2026-08-31

The immutable baseline contains ``artifact_summaries.prompt_version``, but the
staging database was created from an older form of that baseline before the
column was added.  Alembic therefore reports the database at head even though
the deployed ORM cannot query summary rows.  This forward repair is
intentionally idempotent so both histories converge on the same schema.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86d8promptversion"
down_revision: Union[str, None] = "86d7m4q2xpublic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    summary_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("artifact_summaries")
    }
    if "prompt_version" not in summary_columns:
        op.add_column(
            "artifact_summaries",
            sa.Column("prompt_version", sa.String(), nullable=True),
        )


def downgrade() -> None:
    # Do not drop the column: it belongs to the immutable baseline for fresh
    # databases. A downgrade must not recreate the historical schema drift.
    pass
