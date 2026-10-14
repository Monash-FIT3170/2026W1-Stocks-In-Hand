from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote_plus, urlparse
from uuid import UUID

import boto3
from app.messages import PublicDiscussionAnalysisMessage
from parsing.analysis import AnalysisOutput, analyse_document
from pydantic import ValidationError

from app.alert_vocabulary import ALERT_SENTIMENT_LABELS
from app.messages import NotificationMessage
from lambdas import artifact_analysis
from lambdas.artifact_analysis import AlreadyAnalysed, deployed_ports
from lambdas.common import (
    PermanentDocumentError,
    database_session,
    log_event,
)
from app.sources import adapter_matches_ticker
from app.status import AnalysisStatus, DownloadStatus
from lambdas.pipeline_stage import (
    StageRecord,
    analysed_document,
    analysed_stored_text,
    run_stage,
)
from lambdas.raw_documents import (
    DocumentLocation,
    RawDocumentStore,
    locate,
    raw_document_store,
)
from parsing.classification_metadata import merge_classification_metadata

STAGE = "analysis"


def parse_public_discussion_message(
    record: dict,
) -> PublicDiscussionAnalysisMessage | None:
    try:
        body = json.loads(record["body"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict) or body.get("message_type") != (
        "public_discussion_analysis"
    ):
        return None
    try:
        return PublicDiscussionAnalysisMessage.model_validate(body)
    except ValidationError as exc:
        raise PermanentDocumentError(
            "Public discussion analysis message does not match schema version 1",
            code="invalid_message",
        ) from exc


def _artifact_filename(artifact) -> str | None:
    metadata = getattr(artifact, "artifact_metadata", None)
    if isinstance(metadata, dict):
        filename = metadata.get("filename")
        if isinstance(filename, str) and filename.strip():
            return filename.strip()
    for attribute in ("document_url", "url"):
        value = getattr(artifact, attribute, None)
        if isinstance(value, str) and value:
            filename = PurePosixPath(unquote_plus(urlparse(value).path)).name
            if filename:
                return filename
    return None


def parse_s3_notifications(record: dict) -> list[DocumentLocation]:
    """The stored documents a native S3 ObjectCreated notification names."""
    try:
        body = json.loads(record["body"])
        notifications = body["Records"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise PermanentDocumentError(
            "Queue C message is not a native S3 notification",
            code="invalid_s3_event",
        ) from exc

    locations: list[DocumentLocation] = []
    for notification in notifications:
        try:
            event_name = str(notification["eventName"])
            bucket = str(notification["s3"]["bucket"]["name"])
            key = unquote_plus(str(notification["s3"]["object"]["key"]))
        except (KeyError, TypeError) as exc:
            raise PermanentDocumentError(
                "S3 notification is missing object identity",
                code="invalid_s3_event",
            ) from exc
        if not event_name.startswith("ObjectCreated:"):
            raise PermanentDocumentError(
                "S3 notification is not an ObjectCreated event",
                code="invalid_s3_event",
            )
        locations.append(locate(bucket, key))
    if not locations:
        raise PermanentDocumentError(
            "S3 notification contains no records",
            code="empty_s3_event",
        )
    return locations


def _artifact_state(store: RawDocumentStore, location: DocumentLocation) -> dict:
    artifact_id = location.artifact_id
    ticker = location.ticker
    with database_session() as db:
        from app.crud.artifact import get_artifact

        artifact = get_artifact(db, artifact_id)
        if artifact is None:
            raise PermanentDocumentError(
                "Artifact does not exist",
                code="artifact_not_found",
            )
        artifact_ticker = artifact.ticker.symbol if artifact.ticker is not None else None
        if (
            not adapter_matches_ticker(ticker, artifact.source_adapter or "")
            or artifact_ticker != ticker
            or artifact.scrape_run_id is None
        ):
            raise PermanentDocumentError(
                "S3 notification does not identify a supported pipeline artifact",
                code="artifact_identity_mismatch",
            )
        state = {
            "completed": artifact.analysis_status == AnalysisStatus.COMPLETED,
            "run_id": artifact.scrape_run_id,
            "title": artifact.title or "Untitled ASX announcement",
            "download_status": artifact.download_status,
            "s3_bucket": artifact.s3_bucket,
            "s3_key": artifact.s3_key,
            "checksum": artifact.checksum_sha256,
            "source_type": getattr(artifact, "source_type", None),
            "source_adapter": getattr(artifact, "source_adapter", None),
            "filename": _artifact_filename(artifact),
        }

    if state["download_status"] == DownloadStatus.STORED:
        if not location.is_recorded_as(
            s3_bucket=state["s3_bucket"],
            s3_key=state["s3_key"],
            checksum_sha256=state["checksum"],
        ):
            raise PermanentDocumentError(
                "S3 notification is stale or does not match the artifact",
                code="artifact_identity_mismatch",
            )
        return state

    # S3 can deliver ObjectCreated before the downloader commits its database
    # update. Reconcile from the immutable object so the event is not delayed
    # for the queue's 72-minute visibility timeout.
    stored = store.verify(location)
    with database_session() as db:
        from app.crud.scrape_run import mark_artifact_stored

        if mark_artifact_stored(db, artifact_id, **stored.artifact_fields()) is None:
            raise PermanentDocumentError(
                "Artifact does not exist",
                code="artifact_not_found",
            )
    return state


def _incomplete_announcements(limit: int) -> tuple[list[UUID], int]:
    """Analysed announcements whose summary is incomplete, and how many there are."""
    with database_session() as db:
        from app.services import artifact_summary

        return artifact_summary.incomplete_announcements(db, limit=limit)


def _summary_input(artifact_id: UUID) -> dict:
    with database_session() as db:
        from app.crud.artifact import get_artifact

        artifact = get_artifact(db, artifact_id)
        if artifact is None or artifact.analysis_status != AnalysisStatus.COMPLETED:
            raise RuntimeError("Completed artifact is no longer available")
        metadata = (
            artifact.artifact_metadata
            if isinstance(artifact.artifact_metadata, dict)
            else {}
        )
        return {
            "title": artifact.title or "Untitled ASX announcement",
            "category": str(
                metadata.get("category") or artifact.artifact_type or "UNKNOWN"
            ),
            "extracted_data": metadata.get("extracted_data")
            if isinstance(metadata.get("extracted_data"), dict)
            else {},
            "raw_text": artifact.raw_text or "",
        }


def _resummarise_missing_fields(  # pylint: disable=too-many-locals
    *,
    apply: bool,
    limit: int,
) -> dict:
    """Boundedly regenerate incomplete announcement summaries through Bedrock."""
    capped_limit = max(min(limit, 20), 1)
    artifact_ids, total_missing = _incomplete_announcements(capped_limit)
    result: dict[str, object] = {
        "apply": apply,
        "selected": len(artifact_ids),
        "missing_before": total_missing,
        "updated": 0,
        "failed": [],
    }
    if not apply:
        result["artifact_ids"] = [str(artifact_id) for artifact_id in artifact_ids]
        return result

    from app.services import artifact_summary, generation
    from app.crud.artifact import get_artifact

    provider = generation.providers.configured_provider()
    if not provider.name.startswith("bedrock:"):
        raise RuntimeError("Structured summary repair requires Amazon Bedrock")

    for artifact_id in artifact_ids:
        try:
            generated = generation.generate(
                generation.AnnouncementSummary(**_summary_input(artifact_id)),
                provider=provider,
            )
            if isinstance(generated, generation.Unavailable):
                raise RuntimeError(generated.reason)
            summary = artifact_summary.from_generated(generated)
            if not artifact_summary.is_complete(summary, source_type="asx_announcement"):
                raise RuntimeError("Bedrock response omitted structured summary fields")
            with database_session() as db:
                artifact = get_artifact(db, artifact_id)
                if artifact is None:
                    raise RuntimeError("Completed artifact is no longer available")
                artifact_summary.record(db, artifact, summary)
                db.commit()
            result["updated"] = int(result["updated"]) + 1
        # Continue so one malformed model response cannot block the batch.
        except Exception as exc:  # pylint: disable=broad-exception-caught
            result["failed"].append(
                {
                    "artifact_id": str(artifact_id),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    _remaining_ids, remaining = _incomplete_announcements(1)
    result["missing_after"] = remaining
    return result


def _sentiment_values(output: AnalysisOutput) -> dict:
    return {
        "sentiment_label": output.sentiment["sentiment_label"],
        "stance": output.sentiment.get("label"),
        "confidence_score": output.sentiment.get("confidence_score"),
        "model_used": output.sentiment.get("model_used"),
    }


@lru_cache(maxsize=1)
def _notification_sqs_client() -> Any:
    """Reuse the notification queue client within one warm Lambda process."""
    return boto3.client("sqs")


def _publish_notification(
    *,
    artifact_id: UUID,
    ticker: str,
    scrape_run_id: UUID,
    sentiment: dict,
) -> None:
    """Publish one validated notification message to the configured queue."""
    queue_url = os.getenv("NOTIFICATION_QUEUE_URL", "").strip()
    if not queue_url:
        raise RuntimeError("Notification queue URL is not configured")
    message = NotificationMessage(
        artifact_id=artifact_id,
        ticker=ticker,
        scrape_run_id=scrape_run_id,
        sentiment_label=sentiment["sentiment_label"],
        confidence_score=sentiment["confidence_score"],
    )
    _notification_sqs_client().send_message(
        QueueUrl=queue_url,
        MessageBody=message.model_dump_json(),
    )


def _try_publish_notification(  # pylint: disable=too-many-arguments
    *,
    artifact_id: UUID,
    ticker: str,
    scrape_run_id: UUID,
    sentiment: dict,
    correlation: str,
    attempt: int,
) -> None:
    """Publish an eligible result without risking the analysis pipeline."""
    if os.getenv("NOTIFICATIONS_ENABLED", "false").lower() != "true":
        return
    if sentiment.get("sentiment_label") not in ALERT_SENTIMENT_LABELS:
        return
    try:
        _publish_notification(
            artifact_id=artifact_id,
            ticker=ticker,
            scrape_run_id=scrape_run_id,
            sentiment=sentiment,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log_event(
            stage=STAGE,
            event="notification_publish_failed",
            level=logging.ERROR,
            correlation_id=correlation,
            run_id=scrape_run_id,
            artifact_id=artifact_id,
            attempt=attempt,
            error_code=type(exc).__name__,
        )


def _analyse_object(
    *,
    store: RawDocumentStore,
    location: DocumentLocation,
    correlation: str,
    attempt: int,
) -> None:
    started_at = time.monotonic()
    artifact_id = location.artifact_id
    document_format = location.document_format
    state = _artifact_state(store, location)
    if state["completed"]:
        log_event(
            stage=STAGE,
            event="duplicate_skipped",
            started_at=started_at,
            correlation_id=correlation,
            run_id=state["run_id"],
            artifact_id=artifact_id,
            attempt=attempt,
        )
        return

    with database_session() as db:
        from app.crud.scrape_run import mark_artifact_analysis_started

        mark_artifact_analysis_started(db, artifact_id)

    content = store.read(location)
    output = analyse_document(
        content,
        title=state["title"],
        max_pages=int(os.getenv("MAX_PDF_PAGES", "100")),
        document_format=document_format,
        max_ocr_pages=int(os.getenv("MAX_OCR_PAGES", "5")),
        filename=state.get("filename") or location.key.rsplit("/", 1)[-1],
        source_type=state.get("source_type"),
        source_adapter=state.get("source_adapter"),
    )
    if output.parsed.classification is None:
        raise RuntimeError("Analysis output is missing structured classification")
    analysis_metadata = merge_classification_metadata(
        {}, output.parsed.classification
    )
    analysis_metadata.update(
        {
            "extracted_data": output.parsed.extracted_data,
            "page_count": output.parsed.page_count,
            "document_format": document_format,
        }
    )
    sentiment = _sentiment_values(output)

    with database_session() as db:
        from app.crud.artifact import store_artifact_analysis

        store_artifact_analysis(
            db,
            artifact_id=artifact_id,
            raw_text=output.parsed.raw_text,
            metadata=analysis_metadata,
            summary=output.summary,
            sentiment=sentiment,
        )

    with database_session() as db:
        from app.crud.scrape_run import mark_artifact_analysis_completed

        mark_artifact_analysis_completed(db, artifact_id)

    _try_publish_notification(
        artifact_id=artifact_id,
        ticker=location.ticker,
        scrape_run_id=state["run_id"],
        sentiment=sentiment,
        correlation=correlation,
        attempt=attempt,
    )

    log_event(
        stage=STAGE,
        event="completed",
        started_at=started_at,
        correlation_id=correlation,
        run_id=state["run_id"],
        artifact_id=artifact_id,
        attempt=attempt,
        page_count=output.parsed.page_count,
        category=output.parsed.category,
        classification_status=output.parsed.classification.status,
        primary_category=output.parsed.classification.primary_category,
        classification_score=output.parsed.classification.score,
        classifier_version=output.parsed.classification.classifier_version,
        source_adapter=state.get("source_adapter"),
    )


def _analyse(current: StageRecord) -> None:
    stored_text_message = parse_public_discussion_message(current.record)
    if stored_text_message is not None:
        artifact_id = stored_text_message.artifact_id
        current.subject = analysed_stored_text(artifact_id)
        outcome = artifact_analysis.analyse_stored_text(artifact_id, deployed_ports())
        if isinstance(outcome, AlreadyAnalysed):
            current.log("duplicate_skipped", run_id=outcome.run_id)
        else:
            current.log(
                "completed",
                run_id=outcome.run_id,
                category=outcome.category.upper(),
                source_type=outcome.source_type,
            )
        return
    locations = parse_s3_notifications(current.record)
    store = raw_document_store()
    for location in locations:
        current.subject = analysed_document(location.artifact_id)
        if location.bucket != store.name:
            raise PermanentDocumentError(
                "S3 event came from an unexpected bucket",
                code="unexpected_bucket",
            )
        _analyse_object(
            store=store,
            location=location,
            correlation=current.correlation_id,
            attempt=current.attempt,
        )


def handler(event: dict, _context) -> dict:
    if event.get("operation") == "resummarise_missing_fields":
        apply = event.get("apply") is True
        if apply and event.get("confirmation") != "RESUMMARISE_MISSING_FIELDS":
            raise ValueError("Summary repair apply mode requires confirmation")
        return _resummarise_missing_fields(
            apply=apply,
            limit=int(event.get("limit", 10)),
        )
    for record in event.get("Records", []):
        run_stage(STAGE, record, _analyse)
    return {"processed": len(event.get("Records", []))}
