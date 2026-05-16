"""add auth sessions

Revision ID: f5b57d0d4c33
Revises: b4f2e1a09c73
Create Date: 2026-05-15 15:00:00.000000

"""
# Alembic revision: creates the auth_sessions table used for login sessions.
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5b57d0d4c33"
down_revision: Union[str, None] = "b4f2e1a09c73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("investor_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["investor_id"], ["investors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_auth_sessions_investor_id"),
        "auth_sessions",
        ["investor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_sessions_token_hash"),
        "auth_sessions",
        ["token_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_sessions_token_hash"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_investor_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
