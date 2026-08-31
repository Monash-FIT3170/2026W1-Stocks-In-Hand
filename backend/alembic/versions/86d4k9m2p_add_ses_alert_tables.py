"""add SES watchlist alert tables

Revision ID: 86d4k9m2p
Revises: 86d2supabasesecurity
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "86d4k9m2p"
down_revision: Union[str, None] = "86d2supabasesecurity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ALERT_TABLES = (
    "alert_subscriptions",
    "alert_rules",
    "alert_deliveries",
)


def _revoke_data_api_privileges() -> None:
    """Revoke Supabase roles without breaking plain PostgreSQL installs."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL PRIVILEGES ON TABLE
                    public."alert_subscriptions",
                    public."alert_rules",
                    public."alert_deliveries"
                FROM anon;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'authenticated'
            ) THEN
                REVOKE ALL PRIVILEGES ON TABLE
                    public."alert_subscriptions",
                    public."alert_rules",
                    public."alert_deliveries"
                FROM authenticated;
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    op.create_table(
        "alert_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "investor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "verification_status",
            sa.String(),
            nullable=False,
            server_default="unverified",
        ),
        sa.Column(
            "verification_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_delivery_status", sa.String(), nullable=True),
        sa.Column("last_delivery_error_code", sa.String(), nullable=True),
        sa.Column(
            "last_delivery_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "unsubscribe_token_hash",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "verification_status IN "
            "('unverified', 'pending', 'verified', 'failed')",
            name="ck_alert_subscriptions_verification_status",
        ),
        sa.UniqueConstraint(
            "investor_id",
            name="uq_alert_subscriptions_investor_id",
        ),
        sa.UniqueConstraint(
            "unsubscribe_token_hash",
            name="uq_alert_subscriptions_unsubscribe_token_hash",
        ),
    )

    op.create_table(
        "alert_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "investor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ticker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tickers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "rule_type",
            sa.String(),
            nullable=False,
            server_default="sentiment_threshold",
        ),
        sa.Column(
            "sentiment_labels",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY['negative']::varchar[]"),
        ),
        sa.Column(
            "min_confidence",
            sa.Numeric(5, 4),
            nullable=False,
            server_default="0.75",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "min_confidence >= 0 AND min_confidence <= 1",
            name="ck_alert_rules_min_confidence",
        ),
        sa.UniqueConstraint(
            "investor_id",
            "ticker_id",
            "rule_type",
            name="uq_alert_rules_investor_ticker_type",
        ),
    )
    op.create_index(
        "ux_alert_rules_global",
        "alert_rules",
        ["investor_id", "rule_type"],
        unique=True,
        postgresql_where=sa.text("ticker_id IS NULL"),
    )
    op.create_index(
        "ix_alert_rules_ticker_id",
        "alert_rules",
        ["ticker_id"],
    )

    op.create_table(
        "alert_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "investor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "scrape_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scrape_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alert_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="claimed",
        ),
        sa.Column("ses_message_id", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN "
            "('claimed', 'sent', 'rejected', 'failed', 'suppressed_cap', "
            "'suppressed_budget', 'rollup_sent')",
            name="ck_alert_deliveries_status",
        ),
        sa.CheckConstraint(
            "artifact_id IS NOT NULL OR scrape_run_id IS NOT NULL",
            name="ck_alert_deliveries_artifact_or_scrape_run",
        ),
        sa.UniqueConstraint(
            "investor_id",
            "artifact_id",
            name="uq_alert_deliveries_investor_artifact",
        ),
    )
    op.create_index(
        "ux_alert_deliveries_rollup",
        "alert_deliveries",
        ["investor_id", "scrape_run_id"],
        unique=True,
        postgresql_where=sa.text("artifact_id IS NULL"),
    )
    op.create_index(
        "ix_alert_deliveries_investor_scrape_run",
        "alert_deliveries",
        ["investor_id", "scrape_run_id"],
    )
    op.create_index(
        "ix_alert_deliveries_artifact_id",
        "alert_deliveries",
        ["artifact_id"],
    )
    op.create_index(
        "ix_alert_deliveries_scrape_run_id",
        "alert_deliveries",
        ["scrape_run_id"],
    )
    op.create_index(
        "ix_alert_deliveries_rule_id",
        "alert_deliveries",
        ["rule_id"],
    )
    op.create_index(
        "ix_alert_deliveries_sent_at",
        "alert_deliveries",
        ["sent_at"],
    )

    for table in ALERT_TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
    _revoke_data_api_privileges()


def downgrade() -> None:
    op.drop_table("alert_deliveries")
    op.drop_table("alert_rules")
    op.drop_table("alert_subscriptions")
