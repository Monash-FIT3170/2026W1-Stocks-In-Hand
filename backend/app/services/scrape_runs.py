"""Request a scrape run: durable run state first, then one Queue A message.

The API (``POST /scrape/{ticker}``) and the EventBridge schedule both request
runs through ``request_scrape_run``. The caller passes the queue sender, so
each keeps its own SQS client and tests can pass a fake.

The ticker catalogue is authoritative for the source: the run and its
Queue A message always carry the catalogue's adapter and announcements page.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import HttpUrl
from sqlalchemy.orm import Session

from app.crud import scrape_run as scrape_run_crud
from app.messages import QueueAMessage
from app.sources import source_for_ticker
from app.status import RUN_ACTIVE_OR_FINISHED, ScrapeRunStatus

DiscoverySender = Callable[[QueueAMessage], Any]

ENQUEUE_FAILED = "Could not enqueue website discovery"


class DiscoveryEnqueueError(RuntimeError):
    """The run was recorded but its Queue A message could not be sent.

    The run is marked failed, so a repeat request with the same idempotency
    key sends again.
    """


@dataclass(frozen=True)
class RequestedRun:
    scrape_run_id: UUID
    status: ScrapeRunStatus
    # False when an earlier request with the same key already queued the run.
    enqueued: bool


def request_scrape_run(
    db: Session,
    *,
    ticker: str,
    idempotency_key: str,
    send: DiscoverySender,
    trigger_type: str = "manual",
    metadata: Mapping[str, Any] | None = None,
) -> RequestedRun:
    """Create or reuse the run for this key and queue discovery at most once.

    A run that is queued, in progress or finished is returned as it is. A
    run whose earlier send failed, or that was left mid-request, is sent
    again. Raises ``ValueError`` for a ticker outside the catalogue and
    ``DiscoveryEnqueueError`` when the send fails.
    """
    source = source_for_ticker(ticker)
    if source is None:
        raise ValueError(f"'{ticker}' is not in the ticker catalogue")

    run, created = scrape_run_crud.get_or_create_queued_run(
        db,
        ticker=source.ticker,
        source_url=source.source_url,
        idempotency_key=idempotency_key,
        trigger_type=trigger_type,
    )
    run_id: UUID = run.id
    if not created and run.status in RUN_ACTIVE_OR_FINISHED:
        return RequestedRun(
            scrape_run_id=run_id,
            status=ScrapeRunStatus(run.status),
            enqueued=False,
        )
    if not created and run.status == ScrapeRunStatus.FAILED:
        scrape_run_crud.mark_run_enqueueing(db, run_id)

    message = QueueAMessage(
        scrape_run_id=run_id,
        ticker=source.ticker,
        source_url=HttpUrl(source.source_url),
        source_adapter=source.adapter,
        metadata=dict(metadata or {}),
    )
    try:
        send(message)
    except Exception as exc:
        scrape_run_crud.mark_run_discovery_failed(db, run_id, error=ENQUEUE_FAILED)
        raise DiscoveryEnqueueError(ENQUEUE_FAILED) from exc

    scrape_run_crud.mark_run_queued_if_enqueueing(db, run_id)
    return RequestedRun(
        scrape_run_id=run_id,
        status=ScrapeRunStatus.QUEUED,
        enqueued=True,
    )
