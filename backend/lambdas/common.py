from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LOGGER = logging.getLogger("document_pipeline")
LOGGER.setLevel(logging.INFO)
# Matches maxReceiveCount on every pipeline queue's RedrivePolicy in
# infra/template.yaml. A failure on this receive is the last one before SQS
# moves the message to its dead-letter queue.
MAX_RECEIVE_COUNT = 5


class PermanentDocumentError(ValueError):
    """A message or document retry cannot fix."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunsplit(
        (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower(),
            parsed.path or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def log_event(
    *,
    stage: str,
    event: str,
    started_at: float | None = None,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    payload: dict[str, Any] = {"stage": stage, "event": event, **fields}
    if started_at is not None:
        payload["duration_ms"] = round((time.monotonic() - started_at) * 1000)
    LOGGER.log(level, json.dumps(payload, default=str, separators=(",", ":")))


def receive_attempt(record: dict[str, Any]) -> int:
    value = record.get("attributes", {}).get("ApproximateReceiveCount", "1")
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return 1


def is_final_attempt(attempt: int) -> bool:
    """Whether a retryable failure on this receive is terminal."""
    return attempt >= MAX_RECEIVE_COUNT


def correlation_id(record: dict[str, Any]) -> str:
    return str(record.get("messageId") or "unknown")


@contextmanager
def database_session() -> Iterator[Any]:
    # Imported on use: importing the database layer creates the engine, which
    # builds the settings, so a configuration error surfaces in the stage
    # that first opens a session.
    from app.database.connection import SessionLocal

    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
