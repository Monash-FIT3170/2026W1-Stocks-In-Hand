"""Reconcile a deployed stack's queue pipeline with what the template declares.

The resources, outputs and queue settings to check all come from the
template model, so a queue added to the template is checked without editing
a list here. Read-only: it calls cloudformation:ListStackResources,
cloudformation:DescribeStacks and sqs:GetQueueAttributes through the AWS CLI.

    python -m tools.verify_queue_wiring --stack-name stocks-in-hand-staging

Only the standard library and PyYAML are used, so the workflow that runs
this needs no backend dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

from tools.template_model import TemplateModel, getatt_target, template_model

HEALTHY_STATUSES = {"CREATE_COMPLETE", "UPDATE_COMPLETE"}

# Runs one AWS CLI command (without the leading "aws") and returns its JSON.
AwsCli = Callable[..., dict]


@dataclass(frozen=True)
class QueueExpectation:
    queue: str
    queue_output: str
    dead_letter_output: str
    visibility_timeout: int
    retention: int
    dead_letter_retention: int
    max_receive_count: int | None


def pipeline_resources(model: TemplateModel) -> list[str]:
    """Queues, queue policies, the functions and buckets wired to them, and DLQ alarms."""
    queues = set(model.queues())
    resources = set(queues) | set(model.of_type("AWS::SQS::QueuePolicy"))
    for function_id, function in model.functions().items():
        if set(function.consumed_queues) | function.send_message_targets:
            resources.add(function_id)
    for bucket_id in model.of_type("AWS::S3::Bucket"):
        if any(
            getatt_target(notification.get("Queue"), "Arn") in queues
            for notification in model.bucket_queue_notifications(bucket_id)
        ):
            resources.add(bucket_id)
    for dead_letter_queue in model.dead_letter_queues():
        resources.update(model.alarms_watching(dead_letter_queue))
    return sorted(resources)


def queue_outputs(model: TemplateModel) -> list[str]:
    return sorted(
        output for queue_id in model.queues() for output in model.outputs_referencing(queue_id)
    )


def queue_expectations(model: TemplateModel) -> list[QueueExpectation]:
    expectations = []
    for queue_id in sorted(model.consumers()):
        queue = model.queue(queue_id)
        dead_letter_queue = model.queue(queue.dead_letter_queue or "")
        expectations.append(
            QueueExpectation(
                queue=queue_id,
                queue_output=model.outputs_referencing(queue_id)[0],
                dead_letter_output=model.outputs_referencing(dead_letter_queue.logical_id)[0],
                visibility_timeout=queue.visibility_timeout,
                retention=queue.retention,
                dead_letter_retention=dead_letter_queue.retention,
                max_receive_count=queue.max_receive_count,
            )
        )
    return expectations


def verify(model: TemplateModel, aws: AwsCli, stack_name: str) -> tuple[list[str], list[str]]:
    """Return (problems, Markdown summary lines) for the deployed stack."""
    problems: list[str] = []
    summary = [
        "### Staging queue-wiring reconciliation",
        "",
        "| Resource | Status |",
        "| --- | --- |",
    ]

    deployed = {
        resource["LogicalResourceId"]: resource["ResourceStatus"]
        for resource in aws(
            "cloudformation", "list-stack-resources", "--stack-name", stack_name
        )["StackResourceSummaries"]
    }
    for logical_id in pipeline_resources(model):
        status = deployed.get(logical_id)
        summary.append(f"| {logical_id} | {status or 'MISSING'} |")
        if status is None:
            problems.append(f"{logical_id} is missing from {stack_name}")
        elif status not in HEALTHY_STATUSES:
            problems.append(f"{logical_id} is in unhealthy state: {status}")

    [stack] = aws("cloudformation", "describe-stacks", "--stack-name", stack_name)["Stacks"]
    outputs = {
        output["OutputKey"]: output.get("OutputValue") for output in stack.get("Outputs") or []
    }
    summary += ["", "### Queue outputs", ""]
    for output_key in queue_outputs(model):
        value = outputs.get(output_key)
        if not value or value == "None":
            problems.append(f"Stack output {output_key} is missing or empty")
        else:
            summary.append(f"- {output_key} = {value}")

    summary += [
        "",
        "### Deployed queue settings",
        "",
        "| Queue | Visibility timeout | Retention | Redrive |",
        "| --- | --- | --- | --- |",
    ]
    for expected in queue_expectations(model):
        queue_url = outputs.get(expected.queue_output)
        dead_letter_url = outputs.get(expected.dead_letter_output)
        if not queue_url or not dead_letter_url:
            continue
        attributes = _attributes(aws, queue_url)
        dead_letter_attributes = _attributes(aws, dead_letter_url)
        redrive = json.loads(attributes.get("RedrivePolicy") or "{}")
        mismatches = []
        if int(attributes.get("VisibilityTimeout", -1)) != expected.visibility_timeout:
            mismatches.append(f"visibility timeout is not {expected.visibility_timeout}s")
        if int(attributes.get("MessageRetentionPeriod", -1)) != expected.retention:
            mismatches.append(f"retention is not {expected.retention}s")
        if (
            int(dead_letter_attributes.get("MessageRetentionPeriod", -1))
            != expected.dead_letter_retention
        ):
            mismatches.append(f"dead-letter retention is not {expected.dead_letter_retention}s")
        if redrive.get("deadLetterTargetArn") != dead_letter_attributes.get("QueueArn"):
            mismatches.append("redrive does not target its dead-letter queue")
        if (
            expected.max_receive_count is not None
            and int(redrive.get("maxReceiveCount", -1)) != expected.max_receive_count
        ):
            mismatches.append(f"maxReceiveCount is not {expected.max_receive_count}")
        problems += [f"{expected.queue}: {mismatch}" for mismatch in mismatches]
        summary.append(
            f"| {expected.queue} | {attributes.get('VisibilityTimeout')}s | "
            f"{attributes.get('MessageRetentionPeriod')}s | {json.dumps(redrive)} |"
        )
    return problems, summary


def _attributes(aws: AwsCli, queue_url: str) -> dict:
    return aws(
        "sqs", "get-queue-attributes", "--queue-url", queue_url, "--attribute-names", "All"
    ).get("Attributes", {})


def _aws_cli(*args: str) -> dict:
    completed = subprocess.run(  # nosec B603 - fixed AWS CLI argv, no shell
        ["aws", *args, "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout or "{}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stack-name", required=True)
    args = parser.parse_args(argv)

    problems, summary = verify(template_model(), _aws_cli, args.stack_name)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write("\n".join(summary) + "\n")
    else:
        print("\n".join(summary))
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    if problems:
        print(f"{len(problems)} queue-wiring check(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
