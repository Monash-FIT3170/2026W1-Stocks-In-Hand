"""Disabled-by-default EventBridge producer for configured ASX sources."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone

import boto3

from app.messages import QueueAMessage
from app.sources import SOURCES, scheduled_tickers
from lambdas.common import database_session, load_runtime_configuration, log_event

STAGE = "schedule"
MAX_MARKETAUX_TICKERS_PER_RUN = 5
MAX_MARKETAUX_ITEMS_PER_TICKER = 25


def _event_key(event: dict) -> str:
    value = event.get("id") or event.get("time")
    if value:
        return str(value)[:200]
    return datetime.now(timezone.utc).date().isoformat()


def _enabled_tickers() -> list[str]:
    configured = {
        ticker.strip().upper()
        for ticker in os.getenv(
            "SCHEDULED_TICKERS", ",".join(scheduled_tickers())
        ).split(",")
        if ticker.strip()
    }
    return [ticker for ticker in SOURCES if ticker in configured]


def _marketaux_limit() -> int:
    try:
        configured = int(os.getenv("MARKETAUX_PER_TICKER_LIMIT", "10"))
    except ValueError:
        configured = 10
    return max(1, min(configured, MAX_MARKETAUX_ITEMS_PER_TICKER))


def _collect_marketaux_news(tickers: list[str]) -> dict[str, int]:
    """Collect a bounded Marketaux batch after SSM configuration is loaded."""
    result = {
        "marketaux_tickers": 0,
        "marketaux_created": 0,
        "marketaux_analysis_queued": 0,
        "marketaux_errors": 0,
    }
    if os.getenv("MARKETAUX_ENABLED", "false").lower() != "true":
        return result

    # Import after load_runtime_configuration so settings sees the SSM token.
    from app.services import marketaux

    for ticker in tickers[:MAX_MARKETAUX_TICKERS_PER_RUN]:
        result["marketaux_tickers"] += 1
        try:
            with database_session() as db:
                collected = marketaux.fetch_and_store_news(
                    ticker,
                    _marketaux_limit(),
                    db,
                    summarise=False,
                    enqueue_analysis=True,
                )
        except Exception as exc:  # noqa: BLE001
            result["marketaux_errors"] += 1
            log_event(
                stage=STAGE,
                event="marketaux_ticker_failed",
                level=logging.ERROR,
                ticker=ticker,
                error_code=type(exc).__name__,
            )
            continue

        result["marketaux_created"] += int(collected.get("created", 0))
        result["marketaux_analysis_queued"] += int(
            collected.get("analysis_queued", 0)
        )
        provider_errors = int(collected.get("errors", 0))
        result["marketaux_errors"] += provider_errors
        if provider_errors:
            log_event(
                stage=STAGE,
                event="marketaux_ticker_partial",
                level=logging.ERROR,
                ticker=ticker,
                errors=provider_errors,
            )
    return result


def _request_run(
    *,
    ticker: str,
    event_key: str,
    send: Callable[[QueueAMessage], object],
) -> bool:
    """Request one scheduled run; False when this event already queued it."""
    with database_session() as db:
        # Imported after load_runtime_configuration so settings sees the SSM values.
        from app.services.scrape_runs import request_scrape_run

        requested = request_scrape_run(
            db,
            ticker=ticker,
            idempotency_key=f"schedule:{ticker}:{event_key}",
            send=send,
            trigger_type="scheduled",
            metadata={"trigger": "eventbridge"},
        )
    return requested.enqueued


def handler(event: dict, _context) -> dict:
    """Create one durable run per ticker for a single EventBridge event."""
    started_at = time.monotonic()
    load_runtime_configuration()
    queue_url = os.environ["DISCOVERY_QUEUE_URL"]
    sqs = boto3.client("sqs")

    def send(message: QueueAMessage) -> None:
        sqs.send_message(QueueUrl=queue_url, MessageBody=message.model_dump_json())

    event_key = _event_key(event)
    queued = 0
    marketaux_result = {
        "marketaux_tickers": 0,
        "marketaux_created": 0,
        "marketaux_analysis_queued": 0,
        "marketaux_errors": 0,
    }

    try:
        tickers = _enabled_tickers()
        for ticker in tickers:
            queued += int(
                _request_run(ticker=ticker, event_key=event_key, send=send)
            )
        marketaux_result = _collect_marketaux_news(tickers)
        if marketaux_result["marketaux_errors"]:
            raise RuntimeError("Marketaux collection failed")
    except Exception as exc:
        log_event(
            stage=STAGE,
            event="failed",
            started_at=started_at,
            level=logging.ERROR,
            error_code=type(exc).__name__,
            event_id=event_key,
            queued=queued,
            **marketaux_result,
        )
        raise

    log_event(
        stage=STAGE,
        event="completed",
        started_at=started_at,
        event_id=event_key,
        queued=queued,
        **marketaux_result,
    )
    return {
        "queued": queued,
        "event_id": event_key,
        **marketaux_result,
    }
