from __future__ import annotations

import hashlib
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError
from pydantic import ValidationError

from app.messages import QueueBMessage
from lambdas.common import (
    PermanentDocumentError,
    canonicalize_url,
    correlation_id,
    database_session,
    log_event,
    receive_attempt,
)
from lambdas.download_validation import (
    DOCUMENT_CONTENT_TYPES,
    DownloadedDocument,
    validate_document_content,
)

STAGE = "download"
SUPPORTED_ADAPTERS = {
    "ANZ": "anz",
    "BHP": "bhp",
    "CBA": "cba",
    "COH": "coh",
    "COL": "col",
    "CSL": "csl",
    "MQG": "mqg",
    "ORG": "org",
    "RIO": "rio",
    "TCL": "tcl",
    "TLS": "tls",
    "WDS": "wds",
    "WES": "wes",
}


def _parse_message(record: dict) -> QueueBMessage:
    try:
        message = QueueBMessage.model_validate_json(record["body"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise PermanentDocumentError(
            "Queue B message does not match schema version 1",
            code="invalid_message",
        ) from exc
    if SUPPORTED_ADAPTERS.get(message.ticker) != message.source_adapter:
        raise PermanentDocumentError(
            "Ticker and source adapter are not a supported pair",
            code="unsupported_source",
        )
    return message


def _load_artifact(message: QueueBMessage):
    with database_session() as db:
        from app.crud.artifact import get_artifact

        artifact = get_artifact(db, message.artifact_id)
        if artifact is None:
            raise PermanentDocumentError(
                "Artifact does not exist",
                code="artifact_not_found",
            )
        if (
            artifact.scrape_run_id != message.scrape_run_id
            or canonicalize_url(artifact.canonical_url or "")
            != canonicalize_url(str(message.canonical_url))
            or canonicalize_url(artifact.document_url or "")
            != canonicalize_url(str(message.document_url))
        ):
            raise PermanentDocumentError(
                "Queue B identity does not match the artifact",
                code="artifact_identity_mismatch",
            )
        # Return only scalar values; the ORM row is detached after this block.
        return {
            "status": artifact.download_status,
            "s3_bucket": artifact.s3_bucket,
            "s3_key": artifact.s3_key,
        }


def _mark_failed(message: QueueBMessage, error: str) -> None:
    try:
        with database_session() as db:
            from app.crud.scrape_run import mark_artifact_download_failed

            mark_artifact_download_failed(db, message.artifact_id, error=error)
    except Exception:
        log_event(
            stage=STAGE,
            event="state_update_failed",
            level=logging.ERROR,
            run_id=message.scrape_run_id,
            artifact_id=message.artifact_id,
            error_code="database_error",
        )
        # Do not acknowledge a queue message until its failure is durable.
        raise


def _object_exists(s3, *, bucket: str | None, key: str | None) -> bool:
    if not bucket or not key:
        return False
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status in {403, 404}:
            return False
        raise


def _resolve_download(
    message: QueueBMessage,
    *,
    max_bytes: int,
) -> DownloadedDocument:
    # Source adapters own browser/session recreation. S3 persistence remains
    # here so every source receives identical validation and idempotency.
    from lambdas.source_download import resolve_download

    return resolve_download(message, max_bytes=max_bytes)


def _put_immutable_document(
    s3,
    *,
    bucket: str,
    key: str,
    downloaded: DownloadedDocument,
) -> None:
    key_parts = key.split("/")
    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=downloaded.content,
            ContentLength=len(downloaded.content),
            ContentType=downloaded.content_type,
            ServerSideEncryption="AES256",
            Metadata={
                "artifact-id": key_parts[2],
                "sha256": downloaded.checksum,
                "ticker": key_parts[1],
                "document-format": downloaded.document_format,
            },
            IfNoneMatch="*",
        )
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 412 or code in {"PreconditionFailed", "ConditionalRequestConflict"}:
            return
        raise


def _handle_record(record: dict) -> None:
    started_at = time.monotonic()
    correlation = correlation_id(record)
    attempt = receive_attempt(record)
    message: QueueBMessage | None = None

    try:
        message = _parse_message(record)
        artifact_state = _load_artifact(message)
        s3 = boto3.client("s3")
        if artifact_state["status"] == "stored" and _object_exists(
            s3,
            bucket=artifact_state["s3_bucket"],
            key=artifact_state["s3_key"],
        ):
            log_event(
                stage=STAGE,
                event="duplicate_skipped",
                started_at=started_at,
                correlation_id=correlation,
                run_id=message.scrape_run_id,
                artifact_id=message.artifact_id,
                attempt=attempt,
            )
            return

        with database_session() as db:
            from app.crud.scrape_run import mark_artifact_download_started

            mark_artifact_download_started(db, message.artifact_id)

        max_bytes = int(os.getenv("MAX_DOCUMENT_BYTES", "10485760"))
        downloaded = _resolve_download(message, max_bytes=max_bytes)
        if len(downloaded.content) > max_bytes:
            raise PermanentDocumentError(
                "Document is larger than the configured limit",
                code="document_too_large",
            )
        if hashlib.sha256(downloaded.content).hexdigest() != downloaded.checksum:
            raise PermanentDocumentError(
                "Source resolver returned an invalid checksum",
                code="checksum_mismatch",
            )
        validate_document_content(
            downloaded.content,
            declared_content_type=downloaded.content_type,
            final_url=downloaded.final_url,
            expected_format=downloaded.document_format,
        )
        if downloaded.content_type != DOCUMENT_CONTENT_TYPES[downloaded.document_format]:
            raise PermanentDocumentError(
                "Source resolver returned a non-canonical content type",
                code="content_type_mismatch",
            )
        bucket = os.environ["RAW_DOCUMENT_BUCKET"]
        key = (
            f"raw/{message.ticker}/{message.artifact_id}/"
            f"{downloaded.checksum}.{downloaded.extension}"
        )
        _put_immutable_document(
            s3,
            bucket=bucket,
            key=key,
            downloaded=downloaded,
        )

        with database_session() as db:
            from app.crud.scrape_run import mark_artifact_stored

            mark_artifact_stored(
                db,
                message.artifact_id,
                checksum_sha256=downloaded.checksum,
                s3_bucket=bucket,
                s3_key=key,
                content_type=downloaded.content_type,
                file_size_bytes=len(downloaded.content),
            )
        log_event(
            stage=STAGE,
            event="completed",
            started_at=started_at,
            correlation_id=correlation,
            run_id=message.scrape_run_id,
            artifact_id=message.artifact_id,
            attempt=attempt,
            bytes_downloaded=len(downloaded.content),
            document_format=downloaded.document_format,
        )
    except PermanentDocumentError as exc:
        if message is not None and exc.code != "artifact_identity_mismatch":
            _mark_failed(message, f"{exc.code}: {exc}")
        log_event(
            stage=STAGE,
            event="permanent_failure",
            started_at=started_at,
            level=logging.WARNING,
            correlation_id=correlation,
            run_id=message.scrape_run_id if message else None,
            artifact_id=message.artifact_id if message else None,
            attempt=attempt,
            error_code=exc.code,
        )
    except Exception as exc:
        if message is not None:
            _mark_failed(message, f"{type(exc).__name__}: {exc}")
        log_event(
            stage=STAGE,
            event="retryable_failure",
            started_at=started_at,
            level=logging.ERROR,
            correlation_id=correlation,
            run_id=message.scrape_run_id if message else None,
            artifact_id=message.artifact_id if message else None,
            attempt=attempt,
            error_code=type(exc).__name__,
        )
        raise


def handler(event: dict, _context) -> dict:
    for record in event.get("Records", []):
        _handle_record(record)
    return {"processed": len(event.get("Records", []))}
