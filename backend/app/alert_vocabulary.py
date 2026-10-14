"""The words every alert layer shares.

The settings page, the preferences API, rule validation, the analysis
producer and the notification message all accept exactly the alert labels.
The producer used to drop "neutral" while every other layer accepted it, so
neutral-only rules could be saved but never fired.
"""

from enum import StrEnum
from typing import Literal, get_args

AlertSentimentLabel = Literal["positive", "neutral", "negative"]
ALERT_SENTIMENT_LABELS: frozenset[str] = frozenset(get_args(AlertSentimentLabel))
DEFAULT_ALERT_SENTIMENT_LABELS: tuple[str, ...] = ("negative",)


class DeliveryKind(StrEnum):
    """What a delivery sends: one alert, or a scrape run's rollup.

    The kind is not stored. A rollup's ledger row is the one with no artifact.
    """

    DIRECT = "direct"
    ROLLUP = "rollup"
