"""Commit/CI regression tests for the SQS pipeline declared in infra/template.yaml.

These tests never call AWS. They read the template through the template
model (``tools.template_model``) and check two kinds of thing:

- Rules every queue and function must follow, such as "every consumed queue
  has a dead-letter queue" or "every *_QUEUE_URL variable has a SendMessage
  grant". Each rule is also run against a template broken on purpose, so a
  rule that can never fail is caught.
- The pipeline's intended shape: which function consumes and sends to which
  queue, and the S3 to SQS hand-off into the analysis queue.

Companion checks:
- `sam validate --lint` / `cfn-lint` (structural template validity) run in
  the same CI workflow as this file.
- `verify-staging-queue-wiring.yml` reconciles the *deployed* stack with the
  same model after a staging change set is executed.
"""

import copy
from collections.abc import Callable
from pathlib import Path

import pytest

from tools.template_model import (
    TemplateModel,
    getatt_target,
    possible_strings,
    ref_target,
    template_model,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OIDC_TEMPLATE_PATH = REPOSITORY_ROOT / "infra" / "github-oidc.yaml"
QUEUE_CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci-infra-queue-wiring.yml"

# SQS can deliver a message again while a slow batch is still running unless
# the visibility timeout covers the consumer's timeout with room for retries.
# AWS recommends at least six times the function timeout.
VISIBILITY_TIMEOUT_MULTIPLE = 6


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def consumed_queues_have_dead_letter_queue_alarm_and_outputs(model: TemplateModel) -> list[str]:
    queues = model.queues()
    problems = []
    for queue_id in model.consumers():
        dead_letter_queue = queues[queue_id].dead_letter_queue
        if dead_letter_queue not in queues:
            problems.append(f"{queue_id} has no dead-letter queue")
            continue
        if not model.alarms_watching(dead_letter_queue):
            problems.append(f"{dead_letter_queue} has no alarm")
        for exported in (queue_id, dead_letter_queue):
            if not model.outputs_referencing(exported):
                problems.append(f"{exported} has no URL output")
    return problems


def visibility_timeouts_cover_their_consumers(model: TemplateModel) -> list[str]:
    functions = model.functions()
    problems = []
    for queue_id, consumers in model.consumers().items():
        visibility = model.queue(queue_id).visibility_timeout
        for function_id in consumers:
            needed = VISIBILITY_TIMEOUT_MULTIPLE * functions[function_id].timeout
            if visibility < needed:
                problems.append(
                    f"{queue_id} visibility {visibility}s is under {needed}s for {function_id}"
                )
    return problems


def queue_url_variables_have_send_grants(model: TemplateModel) -> list[str]:
    problems = []
    for function in model.functions().values():
        for name, value in function.environment.items():
            queue_id = ref_target(value)
            if name.endswith("_QUEUE_URL") and queue_id not in function.send_message_targets:
                problems.append(f"{function.logical_id}.{name} has no SendMessage grant")
    return problems


def send_grants_have_queue_url_variables(model: TemplateModel) -> list[str]:
    problems = []
    for function in model.functions().values():
        configured = {
            ref_target(value)
            for name, value in function.environment.items()
            if name.endswith("_QUEUE_URL")
        }
        for queue_id in sorted(function.send_message_targets - configured):
            problems.append(f"{function.logical_id} may send to {queue_id} but has no *_QUEUE_URL")
    return problems


def parameter_variables_have_ssm_grants(model: TemplateModel) -> list[str]:
    problems = []
    for function in model.functions().values():
        for name, value in function.environment.items():
            if not name.endswith("_PARAMETER"):
                continue
            for parameter in possible_strings(value):
                if parameter and not function.can_read_parameter(parameter):
                    problems.append(f"{function.logical_id}.{name} cannot read {parameter}")
    return problems


def queues_are_encrypted(model: TemplateModel) -> list[str]:
    return [
        f"{queue_id} is not encrypted"
        for queue_id, queue in model.queues().items()
        if not queue.encrypted
    ]


def dead_letter_queues_outlive_their_sources(model: TemplateModel) -> list[str]:
    queues = model.queues()
    return [
        f"{queue.dead_letter_queue} keeps messages no longer than {queue_id}"
        for queue_id, queue in queues.items()
        if queue.dead_letter_queue in queues
        and queues[queue.dead_letter_queue].retention <= queue.retention
    ]


def dead_letter_queue_alarms_page_the_alarm_topic(model: TemplateModel) -> list[str]:
    problems = []
    for dead_letter_queue in sorted(model.dead_letter_queues()):
        for alarm_id in model.alarms_watching(dead_letter_queue):
            alarm = model.properties(alarm_id)
            if (
                alarm.get("Namespace") != "AWS/SQS"
                or alarm.get("MetricName") != "ApproximateNumberOfMessagesVisible"
                or {"Ref": "AlarmTopic"} not in (alarm.get("AlarmActions") or [])
            ):
                problems.append(f"{alarm_id} does not page AlarmTopic on visible messages")
    return problems


RULES = [
    consumed_queues_have_dead_letter_queue_alarm_and_outputs,
    visibility_timeouts_cover_their_consumers,
    queue_url_variables_have_send_grants,
    send_grants_have_queue_url_variables,
    parameter_variables_have_ssm_grants,
    queues_are_encrypted,
    dead_letter_queues_outlive_their_sources,
    dead_letter_queue_alarms_page_the_alarm_topic,
]


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.__name__)
def test_template_follows_rule(rule: Callable[[TemplateModel], list[str]]) -> None:
    assert rule(template_model()) == []


def _resources(document: dict) -> dict:
    return document["Resources"]


def _properties(document: dict, logical_id: str) -> dict:
    return document["Resources"][logical_id]["Properties"]


def _environment(document: dict, function_id: str) -> dict:
    return _properties(document, function_id)["Environment"]["Variables"]


def _drop_statement(document: dict, function_id: str, sid: str) -> None:
    for policy in _properties(document, function_id)["Policies"]:
        documents = policy["Fn::If"][1:2] if "Fn::If" in policy else [policy]
        for policy_document in documents:
            policy_document["Statement"] = [
                statement
                for statement in policy_document["Statement"]
                if statement.get("Sid") != sid
            ]


BREAKAGES = {
    "dead letter queue removed": (
        consumed_queues_have_dead_letter_queue_alarm_and_outputs,
        lambda d: _properties(d, "DiscoveryQueue").pop("RedrivePolicy"),
    ),
    "dead letter alarm removed": (
        consumed_queues_have_dead_letter_queue_alarm_and_outputs,
        lambda d: _resources(d).pop("NotificationDlqAlarm"),
    ),
    "queue output removed": (
        consumed_queues_have_dead_letter_queue_alarm_and_outputs,
        lambda d: d["Outputs"].pop("DownloadQueueUrl"),
    ),
    "consumer timeout raised": (
        visibility_timeouts_cover_their_consumers,
        lambda d: _properties(d, "AnalysisFunction").update(Timeout=900),
    ),
    "conditional send grant removed": (
        queue_url_variables_have_send_grants,
        lambda d: _drop_statement(d, "AnalysisFunction", "EnqueueNotifications"),
    ),
    "queue variable without grant": (
        queue_url_variables_have_send_grants,
        lambda d: _environment(d, "ApiFunction").update(DOWNLOAD_QUEUE_URL={"Ref": "DownloadQueue"}),
    ),
    "grant without queue variable": (
        send_grants_have_queue_url_variables,
        lambda d: _environment(d, "DiscoveryFunction").pop("DOWNLOAD_QUEUE_URL"),
    ),
    "parameter outside the grant": (
        parameter_variables_have_ssm_grants,
        lambda d: _environment(d, "NotificationFunction").update(
            REDDIT_CLIENT_ID_PARAMETER={"Fn::Sub": "${ParameterPathPrefix}/reddit-client-id"}
        ),
    ),
    "queue encryption removed": (
        queues_are_encrypted,
        lambda d: _properties(d, "AnalysisDeadLetterQueue").pop("SqsManagedSseEnabled"),
    ),
    "dead letter retention shortened": (
        dead_letter_queues_outlive_their_sources,
        lambda d: _properties(d, "DownloadDeadLetterQueue").update(MessageRetentionPeriod=345600),
    ),
    "alarm action removed": (
        dead_letter_queue_alarms_page_the_alarm_topic,
        lambda d: _properties(d, "DiscoveryDlqAlarm").update(AlarmActions=[]),
    ),
}


@pytest.mark.parametrize("breakage", sorted(BREAKAGES))
def test_rule_catches_a_broken_template(breakage: str) -> None:
    rule, break_template = BREAKAGES[breakage]
    document = copy.deepcopy(template_model().document)
    break_template(document)

    assert rule(TemplateModel(document)) != []


def test_every_rule_has_a_breakage() -> None:
    assert {rule for rule, _ in BREAKAGES.values()} == set(RULES)


# ---------------------------------------------------------------------------
# The pipeline's intended shape
# ---------------------------------------------------------------------------

def test_each_queue_has_one_intended_consumer() -> None:
    assert template_model().consumers() == {
        "DiscoveryQueue": ["DiscoveryFunction"],
        "DownloadQueue": ["DownloadFunction"],
        "AnalysisQueue": ["AnalysisFunction"],
        "NotificationQueue": ["NotificationFunction"],
    }


def test_each_function_may_send_only_to_its_next_queues() -> None:
    # Download hands off to Analysis through the S3 raw-object notification,
    # never a direct SendMessage. The API and the schedulers queue stored
    # public discussion and news for analysis.
    sends = {
        function_id: function.send_message_targets
        for function_id, function in template_model().functions().items()
    }

    assert sends == {
        "ApiFunction": {"DiscoveryQueue", "AnalysisQueue"},
        "DiscoveryFunction": {"DownloadQueue"},
        "DownloadFunction": set(),
        "AnalysisFunction": {"NotificationQueue"},
        "NotificationFunction": set(),
        "SchedulerFunction": {"DiscoveryQueue", "AnalysisQueue"},
        "PublicDiscussionSchedulerFunction": {"AnalysisQueue"},
    }


def test_consumers_read_bounded_batches_behind_their_switches() -> None:
    model = template_model()

    def event(function_id: str) -> dict:
        [properties] = model.function(function_id).sqs_events.values()
        return properties

    assert event("DiscoveryFunction")["BatchSize"] == 1
    assert event("DiscoveryFunction")["Enabled"] is True
    assert event("DownloadFunction")["BatchSize"] == 1
    assert event("DownloadFunction")["ScalingConfig"] == {"MaximumConcurrency": 2}
    # 'enable_analysis: false' in deploy-staging.yml must actually stop Queue C.
    assert event("AnalysisFunction")["BatchSize"] == 1
    assert event("AnalysisFunction")["Enabled"] == {"Fn::If": ["IsAnalysisEnabled", True, False]}
    assert event("NotificationFunction")["BatchSize"] == 10
    assert event("NotificationFunction")["Enabled"] == {
        "Fn::If": ["IsNotificationsEnabled", True, False]
    }
    assert event("NotificationFunction")["FunctionResponseTypes"] == ["ReportBatchItemFailures"]


def test_raw_bucket_notifies_analysis_queue_for_raw_prefix_only() -> None:
    model = template_model()
    [notification] = model.bucket_queue_notifications("RawDocumentBucket")

    # The queue policy must exist before S3 registers the notification target.
    assert model.resource("RawDocumentBucket")["DependsOn"] == "AnalysisQueuePolicy"
    assert notification["Event"] == "s3:ObjectCreated:*"
    assert notification["Filter"] == {"S3Key": {"Rules": [{"Name": "prefix", "Value": "raw/"}]}}
    assert getatt_target(notification["Queue"], "Arn") == "AnalysisQueue"


def test_analysis_queue_policy_restricts_bucket_notifications_to_this_account() -> None:
    policy = template_model().properties("AnalysisQueuePolicy")
    [statement] = policy["PolicyDocument"]["Statement"]

    assert policy["Queues"] == [{"Ref": "AnalysisQueue"}]
    assert statement["Principal"] == {"Service": "s3.amazonaws.com"}
    assert statement["Action"] == "sqs:SendMessage"
    assert getatt_target(statement["Resource"], "Arn") == "AnalysisQueue"
    assert statement["Condition"]["StringEquals"] == {"aws:SourceAccount": {"Ref": "AWS::AccountId"}}
    assert possible_strings(statement["Condition"]["ArnLike"]["aws:SourceArn"]) == [
        "arn:${AWS::Partition}:s3:::stocks-in-hand-${Environment}-${AWS::AccountId}-raw"
    ]


# ---------------------------------------------------------------------------
# CI and the staging role
# ---------------------------------------------------------------------------

def test_queue_ci_runs_when_verification_or_oidc_permissions_change() -> None:
    workflow = QUEUE_CI_WORKFLOW.read_text(encoding="utf-8")

    assert "infra/github-oidc.yaml" in workflow
    assert ".github/workflows/verify-staging-queue-wiring.yml" in workflow


def test_staging_github_role_can_read_only_application_queue_attributes() -> None:
    oidc_template = OIDC_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "Sid: InspectStagingQueueAttributes" in oidc_template
    assert "Action: sqs:GetQueueAttributes" in oidc_template
    assert "sqs:${AWS::Region}:${AWS::AccountId}:stocks-in-hand-staging-*" in oidc_template
