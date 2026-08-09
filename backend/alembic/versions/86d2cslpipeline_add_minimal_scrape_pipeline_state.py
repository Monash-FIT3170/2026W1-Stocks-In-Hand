"""add minimal durable CSL scrape pipeline state

Revision ID: 86d2cslpipeline
Revises: 0001_initial_minimal
Create Date: 2026-07-29 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86d2cslpipeline"
down_revision: Union[str, None] = "0001_initial_minimal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scrape_runs", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column(
        "scrape_runs",
        sa.Column("idempotency_key", sa.String(), nullable=True),
    )
    op.add_column(
        "scrape_runs",
        sa.Column(
            "trigger_type",
            sa.String(),
            server_default="manual",
            nullable=False,
        ),
    )
    op.add_column(
        "scrape_runs",
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scrape_runs",
        sa.Column("items_downloaded", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "scrape_runs",
        sa.Column("items_analyzed", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "scrape_runs",
        sa.Column("items_failed", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_unique_constraint(
        "uq_scrape_runs_idempotency_key",
        "scrape_runs",
        ["idempotency_key"],
    )

    op.add_column(
        "artifacts",
        sa.Column("scrape_run_id", sa.UUID(), nullable=True),
    )
    op.add_column("artifacts", sa.Column("source_adapter", sa.String(), nullable=True))
    op.add_column("artifacts", sa.Column("source_id", sa.String(), nullable=True))
    op.add_column(
        "artifacts",
        sa.Column("source_document_identity", sa.String(length=64), nullable=True),
    )
    op.add_column("artifacts", sa.Column("canonical_url", sa.Text(), nullable=True))
    op.add_column("artifacts", sa.Column("document_url", sa.Text(), nullable=True))
    op.add_column(
        "artifacts",
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column("artifacts", sa.Column("content_type", sa.String(), nullable=True))
    op.add_column("artifacts", sa.Column("file_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("artifacts", sa.Column("s3_bucket", sa.String(), nullable=True))
    op.add_column("artifacts", sa.Column("s3_key", sa.Text(), nullable=True))
    op.add_column(
        "artifacts",
        sa.Column(
            "download_status",
            sa.String(),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "artifacts",
        sa.Column(
            "analysis_status",
            sa.String(),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "artifacts",
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("artifacts", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_artifacts_scrape_run_id",
        "artifacts",
        "scrape_runs",
        ["scrape_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_artifacts_scrape_run_id",
        "artifacts",
        ["scrape_run_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_artifacts_run_canonical_url",
        "artifacts",
        ["scrape_run_id", "canonical_url"],
    )
    op.create_unique_constraint(
        "uq_artifacts_source_document_identity",
        "artifacts",
        ["source_document_identity"],
    )

    # Retain the newest legacy result before enforcing one row per artifact.
    op.execute(
        """
        DELETE FROM artifact_summaries
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY artifact_id
                        ORDER BY created_at DESC NULLS LAST, id DESC
                    ) AS duplicate_number
                FROM artifact_summaries
            ) ranked
            WHERE duplicate_number > 1
        )
        """
    )
    op.execute(
        """
        DELETE FROM artifact_sentiments
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY artifact_id
                        ORDER BY created_at DESC NULLS LAST, id DESC
                    ) AS duplicate_number
                FROM artifact_sentiments
            ) ranked
            WHERE duplicate_number > 1
        )
        """
    )
    op.create_unique_constraint(
        "uq_artifact_summaries_artifact",
        "artifact_summaries",
        ["artifact_id"],
    )
    op.create_unique_constraint(
        "uq_artifact_sentiments_artifact",
        "artifact_sentiments",
        ["artifact_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_artifact_sentiments_artifact",
        "artifact_sentiments",
        type_="unique",
    )
    op.drop_constraint(
        "uq_artifact_summaries_artifact",
        "artifact_summaries",
        type_="unique",
    )

    op.drop_constraint(
        "uq_artifacts_source_document_identity",
        "artifacts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_artifacts_run_canonical_url",
        "artifacts",
        type_="unique",
    )
    op.drop_index("ix_artifacts_scrape_run_id", table_name="artifacts")
    op.drop_constraint(
        "fk_artifacts_scrape_run_id",
        "artifacts",
        type_="foreignkey",
    )
    for column in (
        "last_error",
        "analyzed_at",
        "downloaded_at",
        "analysis_status",
        "download_status",
        "s3_key",
        "s3_bucket",
        "file_size_bytes",
        "content_type",
        "checksum_sha256",
        "document_url",
        "canonical_url",
        "source_id",
        "source_document_identity",
        "source_adapter",
        "scrape_run_id",
    ):
        op.drop_column("artifacts", column)

    op.drop_constraint(
        "uq_scrape_runs_idempotency_key",
        "scrape_runs",
        type_="unique",
    )
    for column in (
        "items_failed",
        "items_analyzed",
        "items_downloaded",
        "queued_at",
        "trigger_type",
        "idempotency_key",
        "source_url",
    ):
        op.drop_column("scrape_runs", column)
