"""Producer for stored-text analysis requests."""

from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.messages import PublicDiscussionAnalysisMessage
from app.status import ANALYSIS_QUEUED_OR_DONE


@lru_cache(maxsize=1)
def _sqs_client() -> Any:
    import boto3

    return boto3.client("sqs", region_name=settings.AWS_REGION)


def enqueue_stored_artifact_analysis(artifact_id: UUID) -> str:
    """Queue analysis for text already stored in the artifacts table.

    The legacy wire message name is retained so deployments can process messages
    produced before stored news was added to this queue.
    """
    if not settings.ANALYSIS_QUEUE_URL:
        raise RuntimeError("ANALYSIS_QUEUE_URL is not configured")
    message = PublicDiscussionAnalysisMessage(artifact_id=artifact_id)
    response = _sqs_client().send_message(
        QueueUrl=settings.ANALYSIS_QUEUE_URL,
        MessageBody=message.model_dump_json(),
    )
    return str(response["MessageId"])


def queue_stored_text(db: Session, artifact: Any) -> bool:
    """Send an artifact's stored text for analysis once, if the queue is configured.

    Skips an artifact that is already queued, being analysed or analysed,
    and one with no title or text to analyse. Shared by public discussion,
    Marketaux news and the pending-analysis requeue.
    """
    has_text = (artifact.raw_text or "").strip() or (artifact.title or "").strip()
    if (
        artifact.analysis_status in ANALYSIS_QUEUED_OR_DONE
        or not settings.ANALYSIS_QUEUE_URL
        or not has_text
    ):
        return False
    from app.crud import scrape_run as scrape_run_crud

    enqueue_stored_artifact_analysis(artifact.id)
    scrape_run_crud.mark_inline_artifact_analysis_queued(db, artifact.id)
    return True
