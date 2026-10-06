from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID

import boto3
from pydantic import HttpUrl, ValidationError

from app.messages import QueueAMessage, QueueBMessage
from lambdas.common import (
    PermanentDocumentError,
    canonicalize_url,
    database_session,
)
from lambdas.pipeline_stage import StageRecord, discovery_run, run_stage
from scrapers import registry as scraper_registry

STAGE = "discovery"


def _parse_message(record: dict) -> QueueAMessage:
    try:
        message = QueueAMessage.model_validate_json(record["body"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise PermanentDocumentError(
            "Queue A message does not match schema version 1",
            code="invalid_message",
        ) from exc
    return message


def _queue_document(sqs, queue_url: str, message: QueueBMessage) -> None:
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=message.model_dump_json(),
    )


def _published_at_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bounded_announcements(announcements: list) -> list:
    """Return recent announcements newest-first before database deduplication."""
    lookback_days = max(int(os.getenv("DISCOVERY_LOOKBACK_DAYS", "30")), 1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    return sorted(
        (
            announcement
            for announcement in announcements
            if _published_at_utc(announcement.date) >= cutoff
        ),
        key=lambda announcement: _published_at_utc(announcement.date),
        reverse=True,
    )


def _discover(current: StageRecord) -> None:
    message = _parse_message(current.record)
    current.subject = discovery_run(message.scrape_run_id)
    with database_session() as db:
        from app.crud.scrape_run import (
            get_scrape_run,
            mark_run_discovery_started,
        )

        run = get_scrape_run(db, message.scrape_run_id)
        if run is None:
            raise PermanentDocumentError(
                "Scrape run does not exist",
                code="run_not_found",
            )
        mark_run_discovery_started(db, message.scrape_run_id)

    announcements = _bounded_announcements(
        asyncio.run(scraper_registry.discover(message.ticker))
    )
    queue_url = os.environ["DOWNLOAD_QUEUE_URL"]
    sqs = boto3.client("sqs")
    seen_urls: set[str] = set()
    documents_seen = 0
    documents_queued = 0
    duplicates_skipped = 0
    max_documents = max(int(os.getenv("MAX_DOCUMENTS_PER_RUN", "3")), 1)

    for announcement in announcements:
        if documents_queued >= max_documents:
            break
        if announcement.ticker != message.ticker:
            raise PermanentDocumentError(
                "Source adapter returned an announcement for another ticker",
                code="source_identity_mismatch",
            )
        document_url = str(announcement.pdf_url)
        canonical_url = canonicalize_url(document_url)
        if canonical_url in seen_urls:
            duplicates_skipped += 1
            continue
        seen_urls.add(canonical_url)
        documents_seen += 1
        published_at = _published_at_utc(announcement.date)
        announcement_metadata = {
            **message.metadata,
            **announcement.metadata,
        }
        raw_source_id = announcement_metadata.get("source_id")
        source_id = str(raw_source_id) if raw_source_id is not None else None

        with database_session() as db:
            from app.crud.scrape_run import get_or_create_artifact

            artifact, created = get_or_create_artifact(
                db,
                scrape_run_id=message.scrape_run_id,
                canonical_url=canonical_url,
                document_url=document_url,
                source_adapter=message.source_adapter,
                source_id=source_id,
                title=announcement.title,
                published_at=published_at,
                metadata={
                    **announcement_metadata,
                    "source_adapter": message.source_adapter,
                },
            )
            artifact_id = cast(UUID, artifact.id)
            artifact_run_id = cast(UUID | None, artifact.scrape_run_id)

        # An artifact from a previous run represents a document that has
        # already entered the durable pipeline. Do not pay to process it
        # again. An artifact from this run is re-published so a retry can
        # recover from a database commit followed by an SQS send failure.
        if not created and artifact_run_id != message.scrape_run_id:
            duplicates_skipped += 1
            continue

        _queue_document(
            sqs,
            queue_url,
            QueueBMessage(
                scrape_run_id=message.scrape_run_id,
                artifact_id=artifact_id,
                ticker=message.ticker,
                source_url=message.source_url,
                document_url=HttpUrl(document_url),
                canonical_url=HttpUrl(canonical_url),
                source_adapter=message.source_adapter,
                source_id=source_id,
                title=announcement.title,
                published_at=published_at,
                metadata=announcement_metadata,
            ),
        )
        documents_queued += 1

    with database_session() as db:
        from app.crud.scrape_run import mark_run_discovery_completed

        mark_run_discovery_completed(
            db,
            message.scrape_run_id,
            items_found=documents_queued,
        )
    current.log(
        "completed",
        documents_seen=documents_seen,
        documents_queued=documents_queued,
        duplicates_skipped=duplicates_skipped,
        max_documents=max_documents,
    )


def handler(event: dict, _context) -> dict:
    for record in event.get("Records", []):
        run_stage(STAGE, record, _discover)
    return {"processed": len(event.get("Records", []))}
