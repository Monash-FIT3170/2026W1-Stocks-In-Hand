"""add artifact ticker mentions

Revision ID: 86d5p7k2q
Revises: 86d2supabasesecurity
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86d5p7k2q"
down_revision: Union[str, None] = "86d2supabasesecurity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifact_ticker_mentions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("ticker_id", sa.UUID(), nullable=False),
        sa.Column("match_method", sa.String(length=64), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.Column("matched_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_artifact_ticker_mentions_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ticker_id"],
            ["tickers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            "ticker_id",
            name="uq_artifact_ticker_mentions_artifact_ticker",
        ),
    )
    op.create_index(
        "ix_artifact_ticker_mentions_artifact_id",
        "artifact_ticker_mentions",
        ["artifact_id"],
    )
    op.create_index(
        "ix_artifact_ticker_mentions_ticker_id",
        "artifact_ticker_mentions",
        ["ticker_id"],
    )
    op.execute(
        'ALTER TABLE public."artifact_ticker_mentions" ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL PRIVILEGES ON TABLE public.artifact_ticker_mentions FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL PRIVILEGES ON TABLE public.artifact_ticker_mentions FROM authenticated;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_artifact_ticker_mentions_ticker_id",
        table_name="artifact_ticker_mentions",
    )
    op.drop_index(
        "ix_artifact_ticker_mentions_artifact_id",
        table_name="artifact_ticker_mentions",
    )
    op.drop_table("artifact_ticker_mentions")
