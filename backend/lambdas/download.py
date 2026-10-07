from __future__ import annotations

from pydantic import ValidationError

from app.messages import QueueBMessage
from app.status import DownloadStatus
from lambdas.common import (
    PermanentDocumentError,
    canonicalize_url,
    database_session,
)
from lambdas.download_validation import DownloadedDocument, document_size_limit
from lambdas.pipeline_stage import StageRecord, downloaded_artifact, run_stage
from lambdas.raw_documents import raw_document_store

STAGE = "download"


def _parse_message(record: dict) -> QueueBMessage:
    try:
        message = QueueBMessage.model_validate_json(record["body"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise PermanentDocumentError(
            "Queue B message does not match schema version 1",
            code="invalid_message",
        ) from exc
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


def _resolve_download(
    message: QueueBMessage,
    *,
    max_bytes: int,
) -> DownloadedDocument:
    # Source adapters own browser/session recreation. S3 persistence remains
    # here so every source receives identical validation and idempotency.
    from lambdas.source_download import resolve_download

    return resolve_download(message, max_bytes=max_bytes)


def _download(current: StageRecord) -> None:
    message = _parse_message(current.record)
    current.subject = downloaded_artifact(
        run_id=message.scrape_run_id,
        artifact_id=message.artifact_id,
    )
    artifact_state = _load_artifact(message)
    store = raw_document_store()
    if artifact_state["status"] == DownloadStatus.STORED and store.holds(
        artifact_state["s3_bucket"],
        artifact_state["s3_key"],
    ):
        current.log("duplicate_skipped")
        return

    with database_session() as db:
        from app.crud.scrape_run import mark_artifact_download_started

        mark_artifact_download_started(db, message.artifact_id)

    # A DownloadedDocument has already passed size and format validation.
    downloaded = _resolve_download(message, max_bytes=document_size_limit())
    stored = store.put(
        ticker=message.ticker,
        artifact_id=message.artifact_id,
        document=downloaded,
    )

    with database_session() as db:
        from app.crud.scrape_run import mark_artifact_stored

        mark_artifact_stored(db, message.artifact_id, **stored.artifact_fields())
    current.log(
        "completed",
        bytes_downloaded=len(downloaded.content),
        document_format=downloaded.document_format,
    )


def handler(event: dict, _context) -> dict:
    for record in event.get("Records", []):
        run_stage(STAGE, record, _download)
    return {"processed": len(event.get("Records", []))}
