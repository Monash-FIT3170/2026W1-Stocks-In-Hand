"""Small producer wrapper for the discovery SQS queue."""

from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.messages import QueueAMessage


@lru_cache(maxsize=1)
def _sqs_client() -> Any:
    import boto3

    return boto3.client("sqs", region_name=settings.AWS_REGION)


def enqueue_discovery(message: QueueAMessage) -> str:
    """Send one validated Queue A message and return its AWS message ID."""
    if not settings.DISCOVERY_QUEUE_URL:
        raise RuntimeError("DISCOVERY_QUEUE_URL is not configured")

    response = _sqs_client().send_message(
        QueueUrl=settings.DISCOVERY_QUEUE_URL,
        MessageBody=message.model_dump_json(),
    )
    return str(response["MessageId"])
