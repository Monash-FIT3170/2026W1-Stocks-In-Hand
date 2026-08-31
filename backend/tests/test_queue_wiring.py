"""Commit/CI regression tests for the Discovery -> Download -> Analysis
queue pipeline declared in infra/template.yaml.

These tests never call AWS. They parse the checked-in SAM template as text
and assert that the queues, dead-letter queues, consumers, producers, the
S3-to-SQS hand-off, and the exported outputs stay wired the way the
pipeline design requires. They exist to catch a wiring regression (a
missing RedrivePolicy, a consumer pointed at the wrong queue, a producer
that gains broader `sqs:SendMessage` access than it needs, a dropped
stack output, and similar changes) at commit/PR time, well before anyone
runs a staging deployment.

Companion checks:
- `sam validate --lint` / `cfn-lint` (structural template validity) run in
  the same CI workflow as this file.
- `verify-staging-queue-wiring.yml` reconciles the *deployed* stack after
  a staging change set is executed, which this file cannot do because it
  never touches AWS.
"""

import re
from functools import lru_cache
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPOSITORY_ROOT / "infra" / "template.yaml"
OIDC_TEMPLATE_PATH = REPOSITORY_ROOT / "infra" / "github-oidc.yaml"
STAGING_VERIFICATION_WORKFLOW = (
    REPOSITORY_ROOT / ".github" / "workflows" / "verify-staging-queue-wiring.yml"
)
QUEUE_CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci-infra-queue-wiring.yml"


@lru_cache(maxsize=1)
def _template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _resource(logical_id: str) -> str:
    """Return the YAML body of a top-level `Resources` entry.

    Matches everything indented under `  {logical_id}:` up to the next
    2-space-indented or 0-space-indented key (the next resource, or a
    following top-level section such as `Outputs:`).
    """
    pattern = re.compile(
        rf"\n  {re.escape(logical_id)}:\n(.*?)(?=\n(?:  [A-Za-z]|[A-Za-z]))",
        re.S,
    )
    match = pattern.search(_template())
    assert match, f"Resource '{logical_id}' not found in infra/template.yaml"
    return match.group(1)


def _outputs() -> str:
    marker = "\nOutputs:\n"
    assert marker in _template(), "Outputs section not found in infra/template.yaml"
    return _template().split(marker, 1)[1]


# ---------------------------------------------------------------------------
# Queues and dead-letter queues
# ---------------------------------------------------------------------------

def test_discovery_queue_redrives_to_its_dead_letter_queue() -> None:
    block = _resource("DiscoveryQueue")
    assert "SqsManagedSseEnabled: true" in block
    assert "deadLetterTargetArn: !GetAtt DiscoveryDeadLetterQueue.Arn" in block
    assert "maxReceiveCount: 5" in block


def test_download_queue_redrives_to_its_dead_letter_queue() -> None:
    block = _resource("DownloadQueue")
    assert "SqsManagedSseEnabled: true" in block
    assert "deadLetterTargetArn: !GetAtt DownloadDeadLetterQueue.Arn" in block
    assert "maxReceiveCount: 5" in block


def test_analysis_queue_redrives_to_its_dead_letter_queue() -> None:
    block = _resource("AnalysisQueue")
    assert "SqsManagedSseEnabled: true" in block
    assert "deadLetterTargetArn: !GetAtt AnalysisDeadLetterQueue.Arn" in block
    assert "maxReceiveCount: 5" in block


def test_primary_queues_retain_messages_and_allow_worker_timeouts() -> None:
    expectations = {
        "DiscoveryQueue": "1800",
        "DownloadQueue": "1800",
        "AnalysisQueue": "4320",
    }
    for logical_id, visibility_timeout in expectations.items():
        block = _resource(logical_id)
        assert "MessageRetentionPeriod: 345600" in block, logical_id
        assert f"VisibilityTimeout: {visibility_timeout}" in block, logical_id


def test_dead_letter_queues_retain_failed_messages_for_fourteen_days() -> None:
    for logical_id in (
        "DiscoveryDeadLetterQueue",
        "DownloadDeadLetterQueue",
        "AnalysisDeadLetterQueue",
    ):
        block = _resource(logical_id)
        assert "MessageRetentionPeriod: 1209600" in block, logical_id
        assert "SqsManagedSseEnabled: true" in block, logical_id


# ---------------------------------------------------------------------------
# Consumers (Lambda event source mappings)
# ---------------------------------------------------------------------------

def test_discovery_function_consumes_discovery_queue_one_message_at_a_time() -> None:
    block = _resource("DiscoveryFunction")
    assert "Queue: !GetAtt DiscoveryQueue.Arn" in block
    assert "BatchSize: 1" in block
    assert "Enabled: true" in block


def test_download_function_consumes_download_queue_with_bounded_concurrency() -> None:
    block = _resource("DownloadFunction")
    assert "Queue: !GetAtt DownloadQueue.Arn" in block
    assert "BatchSize: 1" in block
    assert "MaximumConcurrency: 2" in block


def test_analysis_function_consumption_is_gated_by_the_analysis_toggle() -> None:
    block = _resource("AnalysisFunction")
    assert "Queue: !GetAtt AnalysisQueue.Arn" in block
    assert "BatchSize: 1" in block
    assert "Enabled: !If [IsAnalysisEnabled, true, false]" in block, (
        "Queue C consumption must stay conditional on AnalysisEnabled so "
        "'enable_analysis: false' in deploy-staging.yml actually stops it."
    )


# ---------------------------------------------------------------------------
# Producers (least-privilege sqs:SendMessage scoping)
# ---------------------------------------------------------------------------

def test_api_function_may_only_enqueue_to_discovery_and_analysis_queues() -> None:
    # The AnalysisQueue grant backs the public-discussion inline-analysis
    # path (backend/app/services/public_discussion.py); the API must still
    # never write to the Download queue.
    block = _resource("ApiFunction")
    assert "DISCOVERY_QUEUE_URL: !Ref DiscoveryQueue" in block
    assert "ANALYSIS_QUEUE_URL: !Ref AnalysisQueue" in block
    assert "Sid: EnqueueDiscovery" in block
    assert "Sid: EnqueuePublicDiscussionAnalysis" in block
    assert "Resource: !GetAtt DiscoveryQueue.Arn" in block
    assert "Resource: !GetAtt AnalysisQueue.Arn" in block
    assert "DownloadQueue.Arn" not in block


def test_scheduler_function_may_only_enqueue_to_discovery_queue() -> None:
    block = _resource("SchedulerFunction")
    assert "Resource: !GetAtt DiscoveryQueue.Arn" in block
    assert "DownloadQueue.Arn" not in block
    assert "AnalysisQueue.Arn" not in block


def test_discovery_function_may_only_enqueue_to_download_queue() -> None:
    block = _resource("DiscoveryFunction")
    assert "Action: sqs:SendMessage" in block
    assert "Resource: !GetAtt DownloadQueue.Arn" in block
    assert "AnalysisQueue.Arn" not in block


def test_worker_and_scheduler_queue_environment_variables_match_their_targets() -> None:
    expectations = {
        "DiscoveryFunction": ("DOWNLOAD_QUEUE_URL", "DownloadQueue"),
        "SchedulerFunction": ("DISCOVERY_QUEUE_URL", "DiscoveryQueue"),
        "PublicDiscussionSchedulerFunction": ("ANALYSIS_QUEUE_URL", "AnalysisQueue"),
    }
    for function_id, (variable, queue_id) in expectations.items():
        block = _resource(function_id)
        assert f"{variable}: !Ref {queue_id}" in block, function_id


def test_download_function_never_sends_directly_to_analysis_queue() -> None:
    # Download hands off to Analysis exclusively through the S3 raw-object
    # notification, not a direct sqs:SendMessage. If this ever changes it
    # should be a deliberate design change, not a silent permissions creep.
    block = _resource("DownloadFunction")
    assert "sqs:SendMessage" not in block
    assert "AnalysisQueue" not in block


# ---------------------------------------------------------------------------
# S3 -> SQS hand-off into the Analysis queue
# ---------------------------------------------------------------------------

def test_raw_bucket_notifies_analysis_queue_for_raw_prefix_only() -> None:
    block = _resource("RawDocumentBucket")
    assert "DependsOn: AnalysisQueuePolicy" in block, (
        "The bucket must depend on the queue policy so the SQS permission "
        "exists before S3 tries to register the notification target."
    )
    assert "Event: s3:ObjectCreated:*" in block
    assert "Value: raw/" in block
    assert "Queue: !GetAtt AnalysisQueue.Arn" in block


def test_analysis_queue_policy_restricts_bucket_notifications_to_this_account() -> None:
    block = _resource("AnalysisQueuePolicy")
    assert "Service: s3.amazonaws.com" in block
    assert "Action: sqs:SendMessage" in block
    assert "Resource: !GetAtt AnalysisQueue.Arn" in block
    assert "aws:SourceAccount: !Ref AWS::AccountId" in block
    assert "aws:SourceArn: !Sub >-" in block
    assert (
        "arn:${AWS::Partition}:s3:::stocks-in-hand-${Environment}-${AWS::AccountId}-raw"
        in block
    )


# ---------------------------------------------------------------------------
# Monitoring hooks that ride along with the queues
# ---------------------------------------------------------------------------

def test_dlq_alarms_target_their_matching_dead_letter_queue() -> None:
    expectations = {
        "DiscoveryDlqAlarm": "DiscoveryDeadLetterQueue",
        "DownloadDlqAlarm": "DownloadDeadLetterQueue",
        "AnalysisDlqAlarm": "AnalysisDeadLetterQueue",
    }
    for alarm_id, queue_id in expectations.items():
        block = _resource(alarm_id)
        assert "Namespace: AWS/SQS" in block, alarm_id
        assert "MetricName: ApproximateNumberOfMessagesVisible" in block, alarm_id
        assert f"Value: !GetAtt {queue_id}.QueueName" in block, alarm_id
        assert "AlarmActions" in block and "!Ref AlarmTopic" in block, alarm_id


# ---------------------------------------------------------------------------
# Stack outputs the CD integration test relies on
# ---------------------------------------------------------------------------

def test_every_queue_and_dlq_url_is_exported() -> None:
    outputs = _outputs()
    expected_pairs = {
        "DiscoveryQueueUrl": "DiscoveryQueue",
        "DownloadQueueUrl": "DownloadQueue",
        "AnalysisQueueUrl": "AnalysisQueue",
        "DiscoveryDeadLetterQueueUrl": "DiscoveryDeadLetterQueue",
        "DownloadDeadLetterQueueUrl": "DownloadDeadLetterQueue",
        "AnalysisDeadLetterQueueUrl": "AnalysisDeadLetterQueue",
    }
    for output_key, ref_target in expected_pairs.items():
        assert f"{output_key}:\n    Value: !Ref {ref_target}" in outputs, output_key


def test_staging_queue_verification_reads_deployed_queue_attributes() -> None:
    workflow = STAGING_VERIFICATION_WORKFLOW.read_text(encoding="utf-8")

    assert "aws sqs get-queue-attributes" in workflow
    assert "RedrivePolicy" in workflow
    assert "VisibilityTimeout" in workflow
    assert "MessageRetentionPeriod" in workflow
    assert '"maxReceiveCount":"5"' in workflow
    for output_key in (
        "DiscoveryQueueUrl",
        "DownloadQueueUrl",
        "AnalysisQueueUrl",
        "DiscoveryDeadLetterQueueUrl",
        "DownloadDeadLetterQueueUrl",
        "AnalysisDeadLetterQueueUrl",
    ):
        assert output_key in workflow


def test_queue_ci_runs_when_verification_or_oidc_permissions_change() -> None:
    workflow = QUEUE_CI_WORKFLOW.read_text(encoding="utf-8")

    assert "infra/github-oidc.yaml" in workflow
    assert ".github/workflows/verify-staging-queue-wiring.yml" in workflow


def test_staging_github_role_can_read_only_application_queue_attributes() -> None:
    oidc_template = OIDC_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "Sid: InspectStagingQueueAttributes" in oidc_template
    assert "Action: sqs:GetQueueAttributes" in oidc_template
    assert "sqs:${AWS::Region}:${AWS::AccountId}:stocks-in-hand-staging-*" in oidc_template
