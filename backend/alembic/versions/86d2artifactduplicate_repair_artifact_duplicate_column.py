"""repair artifact duplicate column drift

Revision ID: 86d2artifactduplicate
Revises: 86d2cognitoidentity
Create Date: 2026-08-28

The original baseline migration was changed after staging had already applied
it. Fresh databases therefore contain ``artifacts.is_duplicate`` while the
existing staging database does not. This forward repair is intentionally
idempotent so both histories converge on the same schema.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86d2artifactduplicate"
down_revision: Union[str, None] = "86d2cognitoidentity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    artifact_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("artifacts")
    }
    if "is_duplicate" not in artifact_columns:
        op.add_column(
            "artifacts",
            sa.Column(
                "is_duplicate",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    # Do not drop the column: it belongs to the immutable baseline for fresh
    # databases. A downgrade must not recreate the historical schema drift.
    pass
