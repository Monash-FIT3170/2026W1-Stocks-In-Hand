"""One-shot setup for the local pipeline dev loop.

Run by the `pipeline-bootstrap` service in docker-compose.local-pipeline.yml
before any worker starts. Creates the SQS queues and S3 bucket the
discovery/download/analysis workers need against LocalStack, and wires the
raw-document bucket's ObjectCreated notifications to the analysis queue --
mirroring infra/template.yaml's AWS wiring (same S3 "raw/" prefix -> analysis
queue design) so local behaviour matches production. Not used in AWS; the
real stack creates these resources via infra/template.yaml instead.
"""

from __future__ import annotations

import logging
import os

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("local_pipeline_bootstrap")


def _get_or_create_queue(sqs, name: str) -> str:
    try:
        return sqs.get_queue_url(QueueName=name)["QueueUrl"]
    except ClientError:
        LOGGER.info("creating queue %s", name)
        return sqs.create_queue(QueueName=name)["QueueUrl"]


def _queue_arn(sqs, queue_url: str) -> str:
    return sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]


def _get_or_create_bucket(s3, name: str, region: str) -> None:
    try:
        s3.head_bucket(Bucket=name)
        return
    except ClientError:
        LOGGER.info("creating bucket %s", name)
        # S3's CreateBucket rejects an explicit LocationConstraint in
        # us-east-1 but requires one everywhere else.
        if region == "us-east-1":
            s3.create_bucket(Bucket=name)
        else:
            s3.create_bucket(
                Bucket=name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )


def main() -> None:
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    sqs = boto3.client("sqs")
    s3 = boto3.client("s3")

    discovery_url = _get_or_create_queue(sqs, "stocks-in-hand-local-discovery")
    download_url = _get_or_create_queue(sqs, "stocks-in-hand-local-download")
    analysis_url = _get_or_create_queue(sqs, "stocks-in-hand-local-analysis")
    analysis_arn = _queue_arn(sqs, analysis_url)

    bucket = os.environ.get("RAW_DOCUMENT_BUCKET", "stocks-in-hand-local-raw")
    _get_or_create_bucket(s3, bucket, region)

    # Same shape as infra/template.yaml's AnalysisQueuePolicy + the raw
    # bucket's NotificationConfiguration: ObjectCreated under raw/ enqueues
    # straight to the analysis queue, so the download worker never has to
    # know about the analysis queue directly.
    s3.put_bucket_notification_configuration(
        Bucket=bucket,
        NotificationConfiguration={
            "QueueConfigurations": [
                {
                    "QueueArn": analysis_arn,
                    "Events": ["s3:ObjectCreated:*"],
                    "Filter": {
                        "Key": {"FilterRules": [{"Name": "prefix", "Value": "raw/"}]}
                    },
                }
            ]
        },
    )

    LOGGER.info(
        "local pipeline ready: discovery=%s download=%s analysis=%s bucket=%s",
        discovery_url,
        download_url,
        analysis_url,
        bucket,
    )


if __name__ == "__main__":
    main()
