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
from app.services.summary_metadata import (
    combine_summary_text,
    has_complete_summary_metadata,
    normalise_summary_metadata,
)
from parsing.analysis import (
    AnalysisOutput,
    analyse_document,
    analyse_news_text,
    analyse_public_discussion_text,
)
from pydantic import ValidationError

from app.alert_vocabulary import ALERT_SENTIMENT_LABELS
from app.messages import NotificationMessage
from lambdas.common import (
    PermanentDocumentError,
    database_session,
    log_event,
)
from app.sources import adapter_matches_ticker
from app.status import AnalysisStatus, DownloadStatus
from lambdas.download_validation import document_size_limit
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
        if (
            state["s3_bucket"] != location.bucket
            or state["s3_key"] != location.key
            or state["checksum"] != location.checksum
        ):
            raise PermanentDocumentError(
                "S3 notification is stale or does not match the artifact",
                code="artifact_identity_mismatch",
            )
        return state

    # S3 can deliver ObjectCreated before the downloader commits its database
    # update. Reconcile from the immutable object so the event is not delayed
    # for the queue's 72-minute visibility timeout.
    stored_object = store.bucket.head(location.key)
    if stored_object is None:
        raise RuntimeError("Stored object is not visible yet")
    metadata = stored_object.metadata
    content_type = stored_object.content_type
    content_length = stored_object.size
    if (
        metadata.get("artifact-id") != str(artifact_id)
        or metadata.get("sha256") != location.checksum
        or metadata.get("ticker") != ticker
        or metadata.get("document-format") != location.document_format
        or content_type != location.content_type
    ):
        raise PermanentDocumentError(
            "Stored object metadata does not match the S3 event",
            code="artifact_identity_mismatch",
        )
    if content_length > document_size_limit():
        raise PermanentDocumentError(
            "Stored document is larger than the configured limit",
            code="document_too_large",
        )

    with database_session() as db:
        from app.crud.scrape_run import mark_artifact_stored

        artifact = mark_artifact_stored(
            db,
            artifact_id,
            checksum_sha256=location.checksum,
            s3_bucket=location.bucket,
            s3_key=location.key,
            content_type=content_type,
            file_size_bytes=content_length,
        )
        if artifact is None:
            raise PermanentDocumentError(
                "Artifact does not exist",
                code="artifact_not_found",
            )
    return state


def _summary_values(output: AnalysisOutput) -> dict | None:
    if output.summary is None:
        return None
    fields = normalise_summary_metadata(output.summary)
    text = combine_summary_text(fields)
    if not text:
        return None
    return {
        "summary_text": text,
        "model_used": output.summary_model,
        "prompt_version": output.summary_prompt_version,
        **fields,
    }


def _missing_summary_artifact_ids(limit: int) -> tuple[list[UUID], int]:
    """Find completed ASX artifacts missing display or clarity summary fields."""
    with database_session() as db:
        from app.models.artifact import Artifact
        from app.models.artifact_summary import ArtifactSummary

        rows = (
            db.query(Artifact.id, Artifact.artifact_metadata)
            .join(ArtifactSummary, ArtifactSummary.artifact_id == Artifact.id)
            .filter(Artifact.source_type == "asx_announcement")
            .filter(Artifact.analysis_status == AnalysisStatus.COMPLETED)
            .order_by(Artifact.created_at.asc(), Artifact.id.asc())
            .all()
        )
    missing = [
        artifact_id
        for artifact_id, metadata in rows
        if not has_complete_summary_metadata(metadata)
    ]
    return missing[:limit], len(missing)


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
    """Boundedly regenerate missing structured fields through the active LLM."""
    capped_limit = max(min(limit, 20), 1)
    artifact_ids, total_missing = _missing_summary_artifact_ids(capped_limit)
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

    from app.services import llm as llm_service
    from app.crud.artifact import store_artifact_analysis

    model_used = llm_service.active_model_name()
    if not model_used.startswith("bedrock:"):
        raise RuntimeError("Structured summary repair requires Amazon Bedrock")

    for artifact_id in artifact_ids:
        try:
            summary_input = _summary_input(artifact_id)
            summary = llm_service.summarise_announcement(**summary_input)
            fields = normalise_summary_metadata(summary)
            if not has_complete_summary_metadata(fields):
                raise RuntimeError("Bedrock response omitted structured summary fields")
            summary_values = {
                "summary_text": combine_summary_text(fields),
                "model_used": model_used,
                "prompt_version": llm_service.SUMMARY_PROMPT_VERSION,
                **fields,
            }
            with database_session() as db:
                store_artifact_analysis(
                    db,
                    artifact_id=artifact_id,
                    raw_text=summary_input["raw_text"],
                    metadata=fields,
                    summary=summary_values,
                )
            result["updated"] = int(result["updated"]) + 1
        # Continue so one malformed model response cannot block the batch.
        except Exception as exc:  # pylint: disable=broad-exception-caught
            result["failed"].append(
                {
                    "artifact_id": str(artifact_id),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    _remaining_ids, remaining = _missing_summary_artifact_ids(1)
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


def _public_discussion_artifact_state(artifact_id: UUID) -> dict:
    """Load a stored-text artifact for the legacy inline-analysis queue contract."""
    with database_session() as db:
        from app.crud.artifact import get_artifact
        from app.services.public_discussion import PUBLIC_DISCUSSION_SOURCE_TYPES

        artifact = get_artifact(db, artifact_id)
        if artifact is None:
            raise PermanentDocumentError(
                "Artifact does not exist",
                code="artifact_not_found",
            )
        source_type = str(artifact.source_type or "").lower()
        supported_source_types = PUBLIC_DISCUSSION_SOURCE_TYPES | {"news"}
        if source_type not in supported_source_types:
            raise PermanentDocumentError(
                "Artifact is not a supported stored-text source",
                code="artifact_identity_mismatch",
            )
        title = (artifact.title or "").strip()
        raw_text = (artifact.raw_text or "").strip()
        if not title and not raw_text:
            raise PermanentDocumentError(
                "Stored-text artifact has no text",
                code="no_extractable_text",
            )
        metadata = (
            artifact.artifact_metadata
            if isinstance(artifact.artifact_metadata, dict)
            else {}
        )
        source_name = metadata.get("source_name") or metadata.get("provider")
        return {
            "completed": artifact.analysis_status == AnalysisStatus.COMPLETED,
            "run_id": artifact.scrape_run_id,
            "title": title or (
                "Untitled news article"
                if source_type == "news"
                else "Untitled public discussion"
            ),
            "raw_text": raw_text,
            "source_type": source_type,
            "source_name": source_name if isinstance(source_name, str) else None,
        }


def _analyse_public_discussion_artifact(
    *,
    artifact_id: UUID,
    correlation: str,
    attempt: int,
) -> None:
    started_at = time.monotonic()
    state = _public_discussion_artifact_state(artifact_id)
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
        from app.crud.scrape_run import mark_inline_artifact_analysis_started

        mark_inline_artifact_analysis_started(db, artifact_id)

    is_news = state["source_type"] == "news"
    if is_news:
        output = analyse_news_text(
            title=state["title"],
            raw_text=state["raw_text"],
            source_name=state.get("source_name"),
        )
    else:
        output = analyse_public_discussion_text(
            title=state["title"],
            raw_text=state["raw_text"],
            source_type=state["source_type"],
        )

    category = "news_article" if is_news else "user_discussion"

    with database_session() as db:
        from app.crud.artifact import store_artifact_analysis

        store_artifact_analysis(
            db,
            artifact_id=artifact_id,
            raw_text=output.parsed.raw_text,
            metadata={
                "category": category,
                "category_confidence": 1.0,
            },
            summary=_summary_values(output),
            sentiment=_sentiment_values(output),
        )

    with database_session() as db:
        from app.crud.scrape_run import mark_inline_artifact_analysis_completed

        mark_inline_artifact_analysis_completed(db, artifact_id)

    log_event(
        stage=STAGE,
        event="completed",
        started_at=started_at,
        correlation_id=correlation,
        run_id=state["run_id"],
        artifact_id=artifact_id,
        attempt=attempt,
        category=category.upper(),
        source_type=state["source_type"],
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
            summary=_summary_values(output),
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
        current.subject = analysed_stored_text(stored_text_message.artifact_id)
        _analyse_public_discussion_artifact(
            artifact_id=stored_text_message.artifact_id,
            correlation=current.correlation_id,
            attempt=current.attempt,
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
