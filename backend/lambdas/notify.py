"""SQS consumer that delivers database-backed Brevo watchlist alerts.

Each record names one analysed artifact. ``app.services.alert_delivery``
decides what every investor watching its ticker gets, sends it and records
it in the delivery ledger, so a replayed record sends nothing twice. This
handler parses the records, asks for the paced email sender once per
invocation, and returns the records that need another delivery as SQS partial
batch failures. The email boundary is still at least once; that module says
when an email can go out twice.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import ValidationError

from lambdas.common import (
    correlation_id,
    database_session,
    load_runtime_configuration,
    log_event,
    receive_attempt,
)

# Settings and database modules read environment values at import time. Resolve
# encrypted runtime values first, matching the API Lambda cold-start order.
load_runtime_configuration()

# pylint: disable=wrong-import-position
from app.core.config import settings  # noqa: E402
from app.messages import NotificationMessage  # noqa: E402
from app.services import alert_delivery  # noqa: E402
from app.services import email_sender  # noqa: E402


STAGE = "notify"


class PermanentNotificationError(ValueError):
    """A malformed or stale message that a retry cannot repair."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


class RetryableNotificationError(RuntimeError):
    """A dependency or state race that SQS should retry."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def parse_notification_record(record: dict[str, Any]) -> NotificationMessage:
    """Parse one SQS body without logging its potentially private content."""
    try:
        body = record["body"]
        if not isinstance(body, str):
            raise TypeError("SQS body must be a string")
        return NotificationMessage.model_validate_json(body)
    except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise PermanentNotificationError(
            "SQS body does not match notification schema version 1",
            code="invalid_notification_message",
        ) from exc


def _process_record(record: dict[str, Any], sender: email_sender.EmailSender) -> None:
    """Deliver one record's alert to each distinct investor watching its ticker."""
    message = parse_notification_record(record)
    results = alert_delivery.deliver_alerts(
        message,
        sender=sender,
        open_session=database_session,
    )
    for result in results:
        if result.recorded == "suppressed_budget":
            log_event(
                stage=STAGE,
                event="suppressed",
                level=logging.WARNING,
                investor_id=result.investor_id,
                artifact_id=message.artifact_id,
                scrape_run_id=message.scrape_run_id,
                kind=result.kind,
                reason="daily_budget",
            )
    retry_codes = [result.retry_code for result in results if result.retry_code is not None]
    if retry_codes:
        raise RetryableNotificationError(
            "At least one investor delivery needs a retry",
            code=retry_codes[0],
        )


def handler(event: dict[str, Any], _context: Any) -> dict[str, list[dict[str, str]]]:
    """Return exact SQS partial failures while isolating every record."""
    load_runtime_configuration()
    if not settings.NOTIFICATIONS_ENABLED:
        return {"batchItemFailures": []}

    records = event.get("Records", [])
    if not isinstance(records, list):
        log_event(
            stage=STAGE,
            event="invalid_event",
            level=logging.ERROR,
            error_code="records_not_list",
        )
        return {"batchItemFailures": []}

    # Paced senders share ALERT_PACER, so live alerts from this container go
    # out at least a second apart, across records and warm invocations.
    sender = email_sender.configured_sender(paced=True)
    failures: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            log_event(
                stage=STAGE,
                event="record_discarded",
                level=logging.WARNING,
                error_code="invalid_sqs_record",
            )
            continue
        started_at = time.monotonic()
        message_id = correlation_id(record)
        attempt = receive_attempt(record)
        try:
            _process_record(record, sender)
        except (PermanentNotificationError, alert_delivery.AlertMismatch) as exc:
            log_event(
                stage=STAGE,
                event="record_discarded",
                started_at=started_at,
                level=logging.WARNING,
                correlation_id=message_id,
                attempt=attempt,
                error_code=exc.code,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # A raised record would make Lambda retry the entire SQS batch.
            error_code = getattr(exc, "code", type(exc).__name__)
            log_event(
                stage=STAGE,
                event="record_retry",
                started_at=started_at,
                level=logging.ERROR,
                correlation_id=message_id,
                attempt=attempt,
                error_code=error_code,
            )
            if message_id != "unknown":
                failures.append({"itemIdentifier": message_id})
        else:
            log_event(
                stage=STAGE,
                event="record_completed",
                started_at=started_at,
                correlation_id=message_id,
                attempt=attempt,
            )

    return {"batchItemFailures": failures}
