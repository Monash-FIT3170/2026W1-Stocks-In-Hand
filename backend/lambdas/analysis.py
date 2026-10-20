"""The analysis stage: every analysis queue message, through artifact analysis.

The analysis queue carries three kinds of message: a native S3
ObjectCreated notification for each stored document, a stored-text request
for a news or public discussion artifact, and a summary request. The
handler parses each one, names the subject a failure is recorded against,
runs it through ``lambdas.artifact_analysis`` with the deployed ports and
logs the outcome.

A summary request has no subject, so a failure records nothing on the
artifact: a permanent one is logged and dropped, and a retryable one is
retried until it reaches the dead-letter queue.

The IAM-only ``resummarise_missing_fields`` operation completes the
summaries of analysed announcements in bounded batches.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import unquote_plus
from uuid import UUID

from pydantic import ValidationError

from app.messages import AnalysisRequest, SummaryRequestMessage, analysis_request
from lambdas import artifact_analysis
from lambdas.artifact_analysis import (
    AlreadyAnalysed,
    Analysed,
    SummaryUnavailable,
    deployed_ports,
)
from lambdas.common import PermanentDocumentError
from lambdas.pipeline_stage import (
    StageRecord,
    analysed_document,
    analysed_stored_text,
    run_stage,
)
from lambdas.raw_documents import DocumentLocation, locate

STAGE = "analysis"


def parse_analysis_request(record: dict) -> AnalysisRequest | None:
    """The request a message carries, or None for an S3 notification.

    S3 notifications are the queue's only messages without a
    ``message_type``. A request whose type this worker does not know, or
    that does not match its schema, fails as ``invalid_message``.
    """
    try:
        body = json.loads(record["body"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict) or "message_type" not in body:
        return None
    try:
        return analysis_request(body)
    except ValidationError as exc:
        raise PermanentDocumentError(
            "Analysis request does not match schema version 1",
            code="invalid_message",
        ) from exc


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


def _analyse(current: StageRecord) -> None:
    request = parse_analysis_request(current.record)
    if isinstance(request, SummaryRequestMessage):
        _summarise(current, request.artifact_id)
    elif request is not None:
        _analyse_stored_text(current, request.artifact_id)
    else:
        _analyse_stored_documents(current)


def _analyse_stored_documents(current: StageRecord) -> None:
    locations = parse_s3_notifications(current.record)
    ports = deployed_ports()
    for location in locations:
        current.subject = analysed_document(location.artifact_id)
        outcome = artifact_analysis.analyse_stored_document(location, ports)
        if isinstance(outcome, AlreadyAnalysed):
            current.log("duplicate_skipped", run_id=outcome.run_id)
            continue
        if outcome.alert_error is not None:
            current.log(
                "notification_publish_failed",
                level=logging.ERROR,
                run_id=outcome.run_id,
                error_code=outcome.alert_error,
            )
        _log_topic_error(current, outcome)
        classification = outcome.classification
        current.log(
            "completed",
            run_id=outcome.run_id,
            page_count=outcome.page_count,
            category=outcome.category,
            classification_status=classification.status,
            primary_category=classification.primary_category,
            classification_score=classification.score,
            classifier_version=classification.classifier_version,
            source_adapter=outcome.source_adapter,
        )


def _analyse_stored_text(current: StageRecord, artifact_id: UUID) -> None:
    current.subject = analysed_stored_text(artifact_id)
    outcome = artifact_analysis.analyse_stored_text(artifact_id, deployed_ports())
    if isinstance(outcome, AlreadyAnalysed):
        current.log("duplicate_skipped", run_id=outcome.run_id)
        return
    _log_topic_error(current, outcome)
    current.log(
        "completed",
        run_id=outcome.run_id,
        category=outcome.category.upper(),
        source_type=outcome.source_type,
    )


def _log_topic_error(current: StageRecord, outcome: Analysed) -> None:
    """Log content topics that could not be recorded; the analysis itself completed."""
    if outcome.topic_error is not None:
        current.log(
            "content_topics_failed",
            level=logging.WARNING,
            run_id=outcome.run_id,
            error_code=outcome.topic_error,
        )


def _summarise(current: StageRecord, artifact_id: UUID) -> None:
    outcome = artifact_analysis.summarise(artifact_id, deployed_ports())
    if isinstance(outcome, SummaryUnavailable):
        current.log("summary_unavailable", artifact_id=artifact_id, reason=outcome.reason)
        return
    current.log(
        "completed",
        artifact_id=artifact_id,
        model=outcome.model,
        prompt_version=outcome.prompt_version,
        complete=outcome.complete,
    )


def handler(event: dict, _context) -> dict:
    if event.get("operation") == "resummarise_missing_fields":
        apply = event.get("apply") is True
        if apply and event.get("confirmation") != "RESUMMARISE_MISSING_FIELDS":
            raise ValueError("Summary repair apply mode requires confirmation")
        return artifact_analysis.repair_missing_summaries(
            apply=apply,
            limit=int(event.get("limit", 10)),
            ports=deployed_ports(),
        )
    for record in event.get("Records", []):
        run_stage(STAGE, record, _analyse)
    return {"processed": len(event.get("Records", []))}
