from __future__ import annotations

import json
import logging
from urllib.parse import unquote_plus
from uuid import UUID

from pydantic import ValidationError

from app.messages import PublicDiscussionAnalysisMessage
from app.status import AnalysisStatus
from lambdas import artifact_analysis
from lambdas.artifact_analysis import AlreadyAnalysed, deployed_ports
from lambdas.common import PermanentDocumentError, database_session
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
        return _resummarise_missing_fields(
            apply=apply,
            limit=int(event.get("limit", 10)),
        )
    for record in event.get("Records", []):
        run_stage(STAGE, record, _analyse)
    return {"processed": len(event.get("Records", []))}
