"""The words every alert layer shares.

The settings page, the preferences API, rule validation, the analysis
producer and the notification message all accept exactly the alert labels.
The producer used to drop "neutral" while every other layer accepted it, so
neutral-only rules could be saved but never fired.

The CHECK constraints on ``alert_deliveries.status`` and
``alert_subscriptions.verification_status`` (migration ``86d4k9m2p``) accept
exactly the members of ``DeliveryStatus`` and ``VerificationStatus``, so a new
member needs a migration too.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Literal, get_args

AlertSentimentLabel = Literal["positive", "neutral", "negative"]
ALERT_SENTIMENT_LABELS: frozenset[str] = frozenset(get_args(AlertSentimentLabel))
DEFAULT_ALERT_SENTIMENT_LABELS: tuple[str, ...] = ("negative",)
# A new rule wants artifacts at this confidence or more.
DEFAULT_ALERT_MIN_CONFIDENCE = Decimal("0.75")


class DeliveryKind(StrEnum):
    """What a delivery sends: one alert, or a scrape run's rollup.

    The kind is not stored. A rollup's ledger row is the one with no artifact.
    """

    DIRECT = "direct"
    ROLLUP = "rollup"


class DeliveryStatus(StrEnum):
    """Where one delivery ledger row stands."""

    # Claimed before the email is sent, and not finished yet.
    CLAIMED = "claimed"
    SENT = "sent"
    # Will never be sent: the address was refused or is not verified, or the
    # investor's preferences changed before the send.
    REJECTED = "rejected"
    # Not sent this time. A later claim may try again.
    FAILED = "failed"
    # Past the investor's per-run cap. The run's rollup stands in for it.
    SUPPRESSED_CAP = "suppressed_cap"
    # Past the account's daily budget. Dropped for good.
    SUPPRESSED_BUDGET = "suppressed_budget"
    # How a rollup's send is stored.
    ROLLUP_SENT = "rollup_sent"


class VerificationStatus(StrEnum):
    """Whether an alert subscription's address is confirmed."""

    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


# The last delivery statuses the alert settings page reports as a problem.
DELIVERY_PROBLEM_STATUSES: frozenset[DeliveryStatus] = frozenset(
    {DeliveryStatus.FAILED, DeliveryStatus.REJECTED}
)
