"""Database access for investor-wide watchlist alert rules."""

# pylint: disable=not-callable,duplicate-code

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Sequence
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.alert_rule import AlertRule


DEFAULT_RULE_TYPE = "sentiment_threshold"
KNOWN_RULE_TYPES = frozenset({DEFAULT_RULE_TYPE})
KNOWN_SENTIMENT_LABELS = frozenset({"positive", "neutral", "negative"})


def _validate_commit(commit: bool) -> bool:
    """Validate an explicit commit mode before any write is executed."""
    if not isinstance(commit, bool):
        raise ValueError("commit must be a boolean")
    return commit


def _finish_write(db: Session, *, commit: bool) -> None:
    """Commit by default, or leave the caller's transaction open."""
    if commit:
        db.commit()
    else:
        db.flush()


def _normalise_rule_type(rule_type: str) -> str:
    """Return a non-empty, lower-case alert rule type."""
    normalised = str(rule_type).strip().lower()
    if normalised not in KNOWN_RULE_TYPES:
        raise ValueError("rule type must be sentiment_threshold")
    return normalised


def _normalise_sentiment_labels(labels: Sequence[str]) -> list[str]:
    """Return ordered, unique, non-empty sentiment labels."""
    if isinstance(labels, str):
        raise ValueError("sentiment labels must be a sequence of labels")

    normalised: list[str] = []
    for label in labels:
        if not isinstance(label, str):
            raise ValueError("sentiment labels must be strings")
        value = label.strip().lower()
        if not value:
            raise ValueError("sentiment labels must not contain empty values")
        if value not in KNOWN_SENTIMENT_LABELS:
            allowed = ", ".join(sorted(KNOWN_SENTIMENT_LABELS))
            raise ValueError(f"sentiment label must be one of: {allowed}")
        if value not in normalised:
            normalised.append(value)
    if not normalised:
        raise ValueError("sentiment labels must not be empty")
    return normalised


def _normalise_confidence(value: Decimal | float | int) -> Decimal:
    """Validate and return a finite confidence score between zero and one."""
    if isinstance(value, bool):
        raise ValueError("minimum confidence must be a number")
    try:
        confidence = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("minimum confidence must be a number") from exc
    if not confidence.is_finite():
        raise ValueError("minimum confidence must be finite")
    if not Decimal("0") <= confidence <= Decimal("1"):
        raise ValueError("minimum confidence must be between 0 and 1")
    return confidence


def get_default_alert_rule(
    db: Session,
    investor_id: UUID,
    *,
    rule_type: str = DEFAULT_RULE_TYPE,
) -> AlertRule | None:
    """Return an investor's global alert rule for one rule type."""
    normalised_type = _normalise_rule_type(rule_type)
    return (
        db.query(AlertRule)
        .filter(
            AlertRule.investor_id == investor_id,
            AlertRule.ticker_id.is_(None),
            AlertRule.rule_type == normalised_type,
        )
        .first()
    )


def upsert_default_alert_rule(  # pylint: disable=too-many-arguments
    db: Session,
    *,
    investor_id: UUID,
    sentiment_labels: Sequence[str],
    min_confidence: Decimal | float | int,
    enabled: bool,
    rule_type: str = DEFAULT_RULE_TYPE,
    commit: bool = True,
) -> AlertRule:
    """Create or update the global rule using its nullable-key partial index."""
    commit = _validate_commit(commit)
    labels = _normalise_sentiment_labels(sentiment_labels)
    confidence = _normalise_confidence(min_confidence)
    normalised_type = _normalise_rule_type(rule_type)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    statement = insert(AlertRule).values(
        investor_id=investor_id,
        ticker_id=None,
        rule_type=normalised_type,
        sentiment_labels=labels,
        min_confidence=confidence,
        enabled=enabled,
    )
    rule_id = db.execute(
        statement.on_conflict_do_update(
            index_elements=[AlertRule.investor_id, AlertRule.rule_type],
            index_where=AlertRule.ticker_id.is_(None),
            set_={
                "sentiment_labels": statement.excluded.sentiment_labels,
                "min_confidence": statement.excluded.min_confidence,
                "enabled": statement.excluded.enabled,
                "updated_at": func.now(),
            },
        ).returning(AlertRule.id)
    ).scalar_one()
    _finish_write(db, commit=commit)

    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise RuntimeError("alert rule disappeared after upsert")
    db.refresh(rule)
    return rule
