"""Generic long-poll worker that runs a pipeline Lambda handler locally.

AWS invokes lambdas/discovery.py, download.py, and analysis.py's `handler`
functions per-message via an SQS event source mapping. There is no local
equivalent of that, so this script polls a queue in a loop and calls the same
handler function with a hand-built event shaped like the one Lambda passes
it (see `_to_lambda_record`) -- the handler code itself is untouched and
identical to what actually runs in AWS.

Used by docker-compose.local-pipeline.yml, parameterised per worker via
WORKER_HANDLER / WORKER_QUEUE_URL. Not used in AWS.
"""

from __future__ import annotations

import importlib
import logging
import os

import boto3

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("local_worker")


def _load_handler(dotted_path: str):
    module_path, _, function_name = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, function_name)


def _to_lambda_record(message: dict) -> dict:
    """Reshape an SQS receive_message() entry into an SQS-event-source record.

    Real Lambda invocations use lowercase keys (`body`, `attributes`,
    `messageId`); boto3's receive_message() response uses PascalCase
    (`Body`, `Attributes`, `MessageId`). This maps one to the other so the
    handler code doesn't need to know it's running locally.
    """
    return {
        "messageId": message.get("MessageId"),
        "receiptHandle": message.get("ReceiptHandle"),
        "body": message.get("Body", ""),
        "attributes": message.get("Attributes", {}),
    }


def main() -> None:
    handler_path = os.environ["WORKER_HANDLER"]
    queue_url = os.environ["WORKER_QUEUE_URL"]
    poll_seconds = int(os.getenv("WORKER_POLL_SECONDS", "10"))

    handler = _load_handler(handler_path)
    sqs = boto3.client("sqs")

    LOGGER.info("starting: handler=%s queue=%s", handler_path, queue_url)

    while True:
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=poll_seconds,
            AttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        if not messages:
            continue

        for message in messages:
            record = _to_lambda_record(message)
            try:
                handler({"Records": [record]}, None)
            except Exception:
                # A DLQ redrive is AWS-only; locally the message is just left
                # for SQS to redeliver after the visibility timeout, same as
                # a retryable failure in AWS.
                LOGGER.exception(
                    "handler raised for messageId=%s; leaving for redelivery",
                    record["messageId"],
                )
                continue
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])


if __name__ == "__main__":
    main()
