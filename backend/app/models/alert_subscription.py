import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import false, func

from app.alert_vocabulary import VerificationStatus
from app.database.base import Base


_VERIFICATION_STATUSES = ", ".join(f"'{status}'" for status in VerificationStatus)


class AlertSubscription(Base):
    """An investor's confirmed email and watchlist-alert opt-in state."""

    __tablename__ = "alert_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "investor_id",
            name="uq_alert_subscriptions_investor_id",
        ),
        UniqueConstraint(
            "unsubscribe_token_hash",
            name="uq_alert_subscriptions_unsubscribe_token_hash",
        ),
        CheckConstraint(
            f"verification_status IN ({_VERIFICATION_STATUSES})",
            name="ck_alert_subscriptions_verification_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("investors.id", ondelete="CASCADE"),
        nullable=False,
    )
    email = Column(String, nullable=False)
    enabled = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    verification_status = Column(
        String,
        nullable=False,
        default=VerificationStatus.UNVERIFIED,
        server_default=VerificationStatus.UNVERIFIED,
    )
    verification_requested_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    last_delivery_status = Column(String, nullable=True)
    last_delivery_error_code = Column(String, nullable=True)
    last_delivery_at = Column(DateTime(timezone=True), nullable=True)
    unsubscribe_token_hash = Column(String(length=64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
