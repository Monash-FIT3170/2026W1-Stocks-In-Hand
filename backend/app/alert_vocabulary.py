"""Sentiment labels an investor alert rule can match.

The settings page, the preferences API, rule validation, the analysis
producer and the notification message all accept exactly these labels. The
producer used to drop "neutral" while every other layer accepted it, so
neutral-only rules could be saved but never fired.
"""

from typing import Literal, get_args

AlertSentimentLabel = Literal["positive", "neutral", "negative"]
ALERT_SENTIMENT_LABELS: frozenset[str] = frozenset(get_args(AlertSentimentLabel))
DEFAULT_ALERT_SENTIMENT_LABELS: tuple[str, ...] = ("negative",)
