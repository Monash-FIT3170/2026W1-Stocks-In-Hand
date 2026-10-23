"""add pending email change fields to investors

Revision ID: 86d9pendingemail
Revises: 86d9artifacttypes
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86d9pendingemail"
down_revision: Union[str, None] = "86d9artifacttypes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("investors", sa.Column("pending_email", sa.String(), nullable=True))
    op.add_column(
        "investors",
        sa.Column("pending_email_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "investors",
        sa.Column(
            "pending_email_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("investors", "pending_email_requested_at")
    op.drop_column("investors", "pending_email_token_hash")
    op.drop_column("investors", "pending_email")
