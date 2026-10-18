"""add content topics and topic clusters

Revision ID: 86d9contenttopics
Revises: 86d9artifacttypes
Create Date: 2026-10-18

Content topic tagging records the topics each artifact discusses in
``artifact_content_topics`` and groups one ticker's artifacts about one
development in ``content_topic_clusters`` through
``content_topic_cluster_members``. The topic and method CHECK constraints
accept the values in ``app.content_topic_vocabulary`` at this revision; a new
topic needs its own migration.

The tables start empty. ``python -m tools.tag_content_topics`` tags the
artifacts analysed before this revision.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86d9contenttopics"
down_revision: Union[str, None] = "86d9artifacttypes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A snapshot of app.content_topic_vocabulary at this revision.
TOPICS = (
    "earnings_guidance",
    "litigation",
    "regulation",
    "product_launch",
    "macro_exposure",
)
METHODS = ("llm", "rules")
TABLES = (
    "artifact_content_topics",
    "content_topic_clusters",
    "content_topic_cluster_members",
)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.create_table(
        "artifact_content_topics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("event_label", sa.Text(), nullable=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("model_used", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_one_of("topic", TOPICS), name="ck_artifact_content_topics_topic"),
        sa.CheckConstraint(_one_of("method", METHODS), name="ck_artifact_content_topics_method"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_artifact_content_topics_confidence_range",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            "topic",
            name="uq_artifact_content_topics_artifact_topic",
        ),
    )
    op.create_index(
        "ix_artifact_content_topics_artifact_id",
        "artifact_content_topics",
        ["artifact_id"],
    )
    op.create_index(
        "ix_artifact_content_topics_topic_artifact",
        "artifact_content_topics",
        ["topic", "artifact_id"],
    )

    op.create_table(
        "content_topic_clusters",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticker_id", sa.UUID(), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False, server_default=""),
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_one_of("topic", TOPICS), name="ck_content_topic_clusters_topic"),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_topic_clusters_ticker_topic_last",
        "content_topic_clusters",
        ["ticker_id", "topic", "last_published_at"],
    )

    op.create_table(
        "content_topic_cluster_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("cluster_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["cluster_id"], ["content_topic_clusters.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cluster_id",
            "artifact_id",
            name="uq_content_topic_cluster_members_cluster_artifact",
        ),
    )
    op.create_index(
        "ix_content_topic_cluster_members_cluster_id",
        "content_topic_cluster_members",
        ["cluster_id"],
    )
    op.create_index(
        "ix_content_topic_cluster_members_artifact_id",
        "content_topic_cluster_members",
        ["artifact_id"],
    )

    # Supabase's Data API roles get no access, as for every other table.
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    REVOKE ALL PRIVILEGES ON TABLE public.{table} FROM anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL PRIVILEGES ON TABLE public.{table} FROM authenticated;
                END IF;
            END
            $$
            """  # nosec B608 - built only from the fixed table names above
        )


def downgrade() -> None:
    op.drop_index(
        "ix_content_topic_cluster_members_artifact_id",
        table_name="content_topic_cluster_members",
    )
    op.drop_index(
        "ix_content_topic_cluster_members_cluster_id",
        table_name="content_topic_cluster_members",
    )
    op.drop_table("content_topic_cluster_members")
    op.drop_index(
        "ix_content_topic_clusters_ticker_topic_last",
        table_name="content_topic_clusters",
    )
    op.drop_table("content_topic_clusters")
    op.drop_index(
        "ix_artifact_content_topics_topic_artifact",
        table_name="artifact_content_topics",
    )
    op.drop_index(
        "ix_artifact_content_topics_artifact_id",
        table_name="artifact_content_topics",
    )
    op.drop_table("artifact_content_topics")
