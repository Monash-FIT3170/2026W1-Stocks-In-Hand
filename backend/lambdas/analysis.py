from __future__ import annotations

import json
import logging
from urllib.parse import unquote_plus

from pydantic import ValidationError

from app.messages import PublicDiscussionAnalysisMessage
from lambdas import artifact_analysis
from lambdas.artifact_analysis import AlreadyAnalysed, deployed_ports
from lambdas.common import PermanentDocumentError
from lambdas.pipeline_stage import (
    StageRecord,
    analysed_document,
    analysed_stored_text,
    run_stage,
)
from lambdas.raw_documents import DocumentLocation, locate

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
