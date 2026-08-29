"""SQLAlchemy model for the provider-neutral alert delivery ledger."""

# SQLAlchemy exposes ``func.now`` dynamically.
# pylint: disable=not-callable

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database.base import Base


class AlertDelivery(Base):
    """Idempotency and outcome ledger for investor alert deliveries."""

    __tablename__ = "alert_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "investor_id",
            "artifact_id",
            name="uq_alert_deliveries_investor_artifact",
        ),
        Index(
            "ux_alert_deliveries_rollup",
            "investor_id",
            "scrape_run_id",
            unique=True,
            postgresql_where=text("artifact_id IS NULL"),
        ),
        Index(
            "ix_alert_deliveries_investor_scrape_run",
            "investor_id",
            "scrape_run_id",
        ),
        Index("ix_alert_deliveries_artifact_id", "artifact_id"),
        Index("ix_alert_deliveries_scrape_run_id", "scrape_run_id"),
        Index("ix_alert_deliveries_rule_id", "rule_id"),
        Index("ix_alert_deliveries_sent_at", "sent_at"),
        CheckConstraint(
            "status IN "
            "('claimed', 'sent', 'rejected', 'failed', 'suppressed_cap', "
            "'suppressed_budget', 'rollup_sent')",
            name="ck_alert_deliveries_status",
        ),
        CheckConstraint(
            "artifact_id IS NOT NULL OR scrape_run_id IS NOT NULL",
            name="ck_alert_deliveries_artifact_or_scrape_run",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("investors.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=True,
    )
    scrape_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("scrape_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    rule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(
        String,
        nullable=False,
        default="claimed",
        server_default="claimed",
    )
    provider_message_id = Column(String, nullable=True)
    error_code = Column(String, nullable=True)
    error_detail = Column(Text, nullable=True)
    claimed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    sent_at = Column(DateTime(timezone=True), nullable=True)
