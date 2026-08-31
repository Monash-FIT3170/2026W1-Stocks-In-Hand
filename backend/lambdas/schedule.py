"""Disabled-by-default EventBridge producer for configured ASX sources."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

import boto3
from pydantic import HttpUrl

from app.messages import QueueAMessage
from app.sources import SOURCES
from lambdas.common import database_session, load_runtime_configuration, log_event

STAGE = "schedule"
_ACTIVE_OR_FINISHED = {
    "queued",
    "discovering",
    "downloading",
    "analyzing",
    "partial",
    "completed",
}


def _event_key(event: dict) -> str:
    value = event.get("id") or event.get("time")
    if value:
        return str(value)[:200]
    return datetime.now(timezone.utc).date().isoformat()


def _enabled_tickers() -> list[str]:
    configured = {
        ticker.strip().upper()
        for ticker in os.getenv("SCHEDULED_TICKERS", ",".join(SOURCES)).split(",")
        if ticker.strip()
    }
    return [ticker for ticker in SOURCES if ticker in configured]


def _enqueue_ticker(*, ticker: str, event_key: str, sqs, queue_url: str) -> bool:
    source = SOURCES[ticker]
    with database_session() as db:
        from app.crud import scrape_run as scrape_run_crud

        run, created = scrape_run_crud.get_or_create_queued_run(
            db,
            ticker=ticker,
            source_url=source.source_url,
            idempotency_key=f"schedule:{ticker}:{event_key}",
            trigger_type="scheduled",
        )
        if not created and run.status in _ACTIVE_OR_FINISHED:
            return False
        run_id = cast(UUID, run.id)
        if not created and run.status == "failed":
            run = scrape_run_crud.mark_run_enqueueing(db, run_id)
        run_id = cast(UUID, run.id)

    message = QueueAMessage(
        scrape_run_id=run_id,
        ticker=ticker,
        source_url=HttpUrl(source.source_url),
        source_adapter=source.adapter,
        metadata={"trigger": "eventbridge"},
    )
    try:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=message.model_dump_json(),
        )
    except Exception:
        with database_session() as db:
            from app.crud.scrape_run import mark_run_discovery_failed

            mark_run_discovery_failed(
                db,
                run_id,
                error="EventBridge producer could not enqueue discovery",
            )
        raise

    with database_session() as db:
        from app.crud.scrape_run import mark_run_queued_if_enqueueing

        mark_run_queued_if_enqueueing(db, run_id)
    return True


def handler(event: dict, _context) -> dict:
    """Create one durable run per ticker for a single EventBridge event."""
    started_at = time.monotonic()
    load_runtime_configuration()
    queue_url = os.environ["DISCOVERY_QUEUE_URL"]
    sqs = boto3.client("sqs")
    event_key = _event_key(event)
    queued = 0

    try:
        for ticker in _enabled_tickers():
            queued += int(
                _enqueue_ticker(
                    ticker=ticker,
                    event_key=event_key,
                    sqs=sqs,
                    queue_url=queue_url,
                )
            )
    except Exception as exc:
        log_event(
            stage=STAGE,
            event="failed",
            started_at=started_at,
            level=logging.ERROR,
            error_code=type(exc).__name__,
            event_id=event_key,
            queued=queued,
        )
        raise

    log_event(
        stage=STAGE,
        event="completed",
        started_at=started_at,
        event_id=event_key,
        queued=queued,
    )
    return {"queued": queued, "event_id": event_key}
