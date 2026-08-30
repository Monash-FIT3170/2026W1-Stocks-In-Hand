"""Producer for stored-text analysis requests."""

from functools import lru_cache
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.messages import PublicDiscussionAnalysisMessage


@lru_cache(maxsize=1)
def _sqs_client() -> Any:
    import boto3

    return boto3.client("sqs", region_name=settings.AWS_REGION)


def enqueue_public_discussion_analysis(artifact_id: UUID) -> str:
    if not settings.ANALYSIS_QUEUE_URL:
        raise RuntimeError("ANALYSIS_QUEUE_URL is not configured")
    message = PublicDiscussionAnalysisMessage(artifact_id=artifact_id)
    response = _sqs_client().send_message(
        QueueUrl=settings.ANALYSIS_QUEUE_URL,
        MessageBody=message.model_dump_json(),
    )
    return str(response["MessageId"])
