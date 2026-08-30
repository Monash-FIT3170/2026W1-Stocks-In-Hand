from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from functools import lru_cache
from typing import Any
from urllib.parse import unquote_plus
from uuid import UUID

import boto3
from app.messages import PublicDiscussionAnalysisMessage
from parsing.analysis import (
    AnalysisOutput,
    analyse_document,
    analyse_public_discussion_text,
)
from pydantic import ValidationError

from app.messages import NotificationMessage
from lambdas.common import (
    PermanentDocumentError,
    correlation_id,
    database_session,
    log_event,
    receive_attempt,
)
from lambdas.download_validation import (
    DOCUMENT_CONTENT_TYPES,
    DocumentFormat,
    validate_document_content,
)

STAGE = "analysis"
SUPPORTED_TICKERS = frozenset({"ANZ", "BHP", "CBA", "CSL", "WES"})
FORMAT_BY_EXTENSION: dict[str, DocumentFormat] = {
    "pdf": "pdf",
    "txt": "txt",
    "html": "html",
    "docx": "docx",
}
OBJECT_KEY = re.compile(
    r"^raw/(?P<ticker>ANZ|BHP|CBA|CSL|WES)/"
    r"(?P<artifact_id>[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})/"
    r"(?P<checksum>[0-9a-f]{64})\.(?P<extension>pdf|txt|html|docx)$",
    re.IGNORECASE,
)


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


def parse_s3_notifications(
    record: dict,
) -> list[tuple[str, str, str, UUID, str, DocumentFormat]]:
    try:
        body = json.loads(record["body"])
        notifications = body["Records"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise PermanentDocumentError(
            "Queue C message is not a native S3 notification",
            code="invalid_s3_event",
        ) from exc

    parsed: list[tuple[str, str, str, UUID, str, DocumentFormat]] = []
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
        match = OBJECT_KEY.fullmatch(key)
        if not match:
            raise PermanentDocumentError(
                "S3 object key does not match the immutable document layout",
                code="invalid_object_key",
            )
        parsed.append(
            (
                bucket,
                key,
                match.group("ticker").upper(),
                UUID(match.group("artifact_id")),
                match.group("checksum").lower(),
                FORMAT_BY_EXTENSION[match.group("extension").lower()],
            )
        )
    if not parsed:
        raise PermanentDocumentError(
            "S3 notification contains no records",
            code="empty_s3_event",
        )
    return parsed


def _artifact_state(
    *,
    s3,
    artifact_id: UUID,
    bucket: str,
    key: str,
    checksum: str,
    ticker: str,
    document_format: DocumentFormat,
) -> dict:
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
            artifact.source_adapter != ticker.lower()
            or artifact_ticker != ticker
            or ticker not in SUPPORTED_TICKERS
            or artifact.scrape_run_id is None
        ):
            raise PermanentDocumentError(
                "S3 notification does not identify a supported pipeline artifact",
                code="artifact_identity_mismatch",
            )
        state = {
            "completed": artifact.analysis_status == "completed",
            "run_id": artifact.scrape_run_id,
            "title": artifact.title or "Untitled ASX announcement",
            "download_status": artifact.download_status,
            "s3_bucket": artifact.s3_bucket,
            "s3_key": artifact.s3_key,
            "checksum": artifact.checksum_sha256,
        }

    if state["download_status"] == "stored":
        if (
            state["s3_bucket"] != bucket
            or state["s3_key"] != key
            or state["checksum"] != checksum
        ):
            raise PermanentDocumentError(
                "S3 notification is stale or does not match the artifact",
                code="artifact_identity_mismatch",
            )
        return state

    # S3 can deliver ObjectCreated before the downloader commits its database
    # update. Reconcile from the immutable object so the event is not delayed
    # for the queue's 72-minute visibility timeout.
    response = s3.head_object(Bucket=bucket, Key=key)
    content_type = (
        str(response.get("ContentType", ""))
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    content_length = int(response.get("ContentLength", 0))
    metadata = {
        str(name).lower(): str(value)
        for name, value in (response.get("Metadata") or {}).items()
    }
    if (
        metadata.get("artifact-id") != str(artifact_id)
        or metadata.get("sha256") != checksum
        or metadata.get("ticker") != ticker
        or metadata.get("document-format") != document_format
        or content_type != DOCUMENT_CONTENT_TYPES[document_format]
    ):
        raise PermanentDocumentError(
            "Stored object metadata does not match the S3 event",
            code="artifact_identity_mismatch",
        )
    if content_length > int(os.getenv("MAX_DOCUMENT_BYTES", "10485760")):
        raise PermanentDocumentError(
            "Stored document is larger than the configured limit",
            code="document_too_large",
        )

    with database_session() as db:
        from app.crud.scrape_run import mark_artifact_stored

        artifact = mark_artifact_stored(
            db,
            artifact_id,
            checksum_sha256=checksum,
            s3_bucket=bucket,
            s3_key=key,
            content_type=content_type,
            file_size_bytes=content_length,
        )
        if artifact is None:
            raise PermanentDocumentError(
                "Artifact does not exist",
                code="artifact_not_found",
            )
    return state


def _read_s3_document(
    s3,
    *,
    bucket: str,
    key: str,
    checksum: str,
    document_format: DocumentFormat,
) -> bytes:
    max_bytes = int(os.getenv("MAX_DOCUMENT_BYTES", "10485760"))
    response = s3.get_object(Bucket=bucket, Key=key)
    content_type = (
        str(response.get("ContentType", ""))
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if content_type != DOCUMENT_CONTENT_TYPES[document_format]:
        raise PermanentDocumentError(
            "Stored document content type does not match its immutable key",
            code="content_type_mismatch",
        )
    if int(response.get("ContentLength", 0)) > max_bytes:
        raise PermanentDocumentError(
            "Stored document is larger than the configured limit",
            code="document_too_large",
        )
    body = response["Body"]
    try:
        content = body.read(max_bytes + 1)
    finally:
        body.close()
    if len(content) > max_bytes:
        raise PermanentDocumentError(
            "Stored document is larger than the configured limit",
            code="document_too_large",
        )
    if hashlib.sha256(content).hexdigest() != checksum:
        raise PermanentDocumentError(
            "Stored document checksum does not match its immutable key",
            code="checksum_mismatch",
        )
    validate_document_content(
        content,
        declared_content_type=DOCUMENT_CONTENT_TYPES[document_format],
        final_url=key,
        expected_format=document_format,
    )
    return content


def _summary_values(output: AnalysisOutput) -> dict | None:
    if output.summary is None:
        return None
    text = "\n\n".join(
        value.strip()
        for key in ("summary", "about", "changed", "matters")
        if isinstance((value := output.summary.get(key)), str) and value.strip()
    )
    if not text:
        return None
    return {
        "summary_text": text,
        "model_used": output.summary_model,
        "prompt_version": output.summary_prompt_version,
    }


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
    if sentiment.get("sentiment_label") not in {"negative", "positive"}:
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


def _mark_failed(artifact_id: UUID, error: str) -> None:
    try:
        with database_session() as db:
            from app.crud.scrape_run import mark_artifact_analysis_failed

            mark_artifact_analysis_failed(db, artifact_id, error=error)
    except Exception:
        log_event(
            stage=STAGE,
            event="state_update_failed",
            level=logging.ERROR,
            artifact_id=artifact_id,
            error_code="database_error",
        )
        # Do not acknowledge a queue message until its failure is durable.
        raise


def _mark_public_discussion_failed(artifact_id: UUID, error: str) -> None:
    try:
        with database_session() as db:
            from app.crud.scrape_run import mark_inline_artifact_analysis_failed

            mark_inline_artifact_analysis_failed(db, artifact_id, error=error)
    except Exception:
        log_event(
            stage=STAGE,
            event="state_update_failed",
            level=logging.ERROR,
            artifact_id=artifact_id,
            error_code="database_error",
        )
        raise


def _public_discussion_artifact_state(artifact_id: UUID) -> dict:
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
        if source_type not in PUBLIC_DISCUSSION_SOURCE_TYPES:
            raise PermanentDocumentError(
                "Artifact is not a supported public discussion source",
                code="artifact_identity_mismatch",
            )
        title = (artifact.title or "").strip()
        raw_text = (artifact.raw_text or "").strip()
        if not title and not raw_text:
            raise PermanentDocumentError(
                "Public discussion artifact has no stored text",
                code="no_extractable_text",
            )
        return {
            "completed": artifact.analysis_status == "completed",
            "run_id": artifact.scrape_run_id,
            "title": title or "Untitled public discussion",
            "raw_text": raw_text,
            "source_type": source_type,
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

    output = analyse_public_discussion_text(
        title=state["title"],
        raw_text=state["raw_text"],
        source_type=state["source_type"],
    )

    with database_session() as db:
        from app.crud.artifact import store_artifact_analysis

        store_artifact_analysis(
            db,
            artifact_id=artifact_id,
            raw_text=output.parsed.raw_text,
            metadata={
                "category": "user_discussion",
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
        category="USER_DISCUSSION",
        source_type=state["source_type"],
    )


def _analyse_object(
    *,
    s3,
    bucket: str,
    key: str,
    artifact_id: UUID,
    checksum: str,
    ticker: str,
    document_format: DocumentFormat,
    correlation: str,
    attempt: int,
) -> None:
    started_at = time.monotonic()
    state = _artifact_state(
        s3=s3,
        artifact_id=artifact_id,
        bucket=bucket,
        key=key,
        checksum=checksum,
        ticker=ticker,
        document_format=document_format,
    )
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

    content = _read_s3_document(
        s3,
        bucket=bucket,
        key=key,
        checksum=checksum,
        document_format=document_format,
    )
    output = analyse_document(
        content,
        title=state["title"],
        max_pages=int(os.getenv("MAX_PDF_PAGES", "100")),
        document_format=document_format,
        max_ocr_pages=int(os.getenv("MAX_OCR_PAGES", "5")),
    )
    sentiment = _sentiment_values(output)

    with database_session() as db:
        from app.crud.artifact import store_artifact_analysis

        store_artifact_analysis(
            db,
            artifact_id=artifact_id,
            raw_text=output.parsed.raw_text,
            metadata={
                "category": output.parsed.category,
                "category_confidence": output.parsed.category_confidence,
                "extracted_data": output.parsed.extracted_data,
                "page_count": output.parsed.page_count,
                "document_format": document_format,
            },
            summary=_summary_values(output),
            sentiment=sentiment,
        )

    with database_session() as db:
        from app.crud.scrape_run import mark_artifact_analysis_completed

        mark_artifact_analysis_completed(db, artifact_id)

    _try_publish_notification(
        artifact_id=artifact_id,
        ticker=ticker,
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
    )


def _handle_record(record: dict) -> None:
    correlation = correlation_id(record)
    attempt = receive_attempt(record)
    artifact_id: UUID | None = None
    public_discussion_message: PublicDiscussionAnalysisMessage | None = None
    started_at = time.monotonic()
    try:
        public_discussion_message = parse_public_discussion_message(record)
        if public_discussion_message is not None:
            artifact_id = public_discussion_message.artifact_id
            _analyse_public_discussion_artifact(
                artifact_id=artifact_id,
                correlation=correlation,
                attempt=attempt,
            )
            return
        notifications = parse_s3_notifications(record)
        s3 = boto3.client("s3")
        expected_bucket = os.environ["RAW_DOCUMENT_BUCKET"]
        for bucket, key, ticker, artifact_id, checksum, document_format in notifications:
            if bucket != expected_bucket:
                raise PermanentDocumentError(
                    "S3 event came from an unexpected bucket",
                    code="unexpected_bucket",
                )
            _analyse_object(
                s3=s3,
                bucket=bucket,
                key=key,
                artifact_id=artifact_id,
                checksum=checksum,
                ticker=ticker,
                document_format=document_format,
                correlation=correlation,
                attempt=attempt,
            )
    except PermanentDocumentError as exc:
        untrusted_event_errors = {
            "artifact_identity_mismatch",
            "artifact_not_found",
            "unexpected_bucket",
        }
        if artifact_id is not None and exc.code not in untrusted_event_errors:
            if public_discussion_message is not None:
                _mark_public_discussion_failed(artifact_id, f"{exc.code}: {exc}")
            else:
                _mark_failed(artifact_id, f"{exc.code}: {exc}")
        log_event(
            stage=STAGE,
            event="permanent_failure",
            started_at=started_at,
            level=logging.WARNING,
            correlation_id=correlation,
            artifact_id=artifact_id,
            attempt=attempt,
            error_code=exc.code,
        )
    except Exception as exc:
        if artifact_id is not None:
            if public_discussion_message is not None:
                _mark_public_discussion_failed(
                    artifact_id,
                    f"{type(exc).__name__}: {exc}",
                )
            else:
                _mark_failed(artifact_id, f"{type(exc).__name__}: {exc}")
        log_event(
            stage=STAGE,
            event="retryable_failure",
            started_at=started_at,
            level=logging.ERROR,
            correlation_id=correlation,
            artifact_id=artifact_id,
            attempt=attempt,
            error_code=type(exc).__name__,
        )
        raise


def handler(event: dict, _context) -> dict:
    for record in event.get("Records", []):
        _handle_record(record)
    return {"processed": len(event.get("Records", []))}
