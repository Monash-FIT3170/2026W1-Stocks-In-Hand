"""Commit/CI regression tests for the SQS pipeline declared in infra/template.yaml.

These tests never call AWS. They read the template through the template
model (``tools.template_model``) and check two kinds of thing:

- Rules every queue and function must follow, such as "every consumed queue
  has a dead-letter queue" or "every *_QUEUE_URL variable has a SendMessage
  grant". The runtime configuration's rules check each function's
  environment against ``app.core.config``: its variables, values and secrets.
  Each rule is also run against a template broken on purpose, so a rule that
  can never fail is caught.
- The pipeline's intended shape: which function consumes and sends to which
  queue, and the S3 to SQS hand-off into the analysis queue.

Companion checks:
- `sam validate --lint` / `cfn-lint` (structural template validity) run in
  the same CI workflow as this file.
- `verify-staging-queue-wiring.yml` reconciles the *deployed* stack with the
  same model after a staging change set is executed. `test_github_oidc.py`
  checks that its deploy role may read the queue attributes.
"""

import copy
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.config import SECRETS, declared_settings
from tools import verify_queue_wiring
from tools.template_model import (
    TemplateModel,
    getatt_target,
    possible_strings,
    ref_target,
    template_model,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
QUEUE_CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci-infra-queue-wiring.yml"
STAGING_VERIFICATION_WORKFLOW = (
    REPOSITORY_ROOT / ".github" / "workflows" / "verify-staging-queue-wiring.yml"
)

# SQS can deliver a message again while a slow batch is still running unless
# the visibility timeout covers the consumer's timeout with room for retries.
# AWS recommends at least six times the function timeout.
VISIBILITY_TIMEOUT_MULTIPLE = 6
# Template values that differ from the declared default on purpose.
DELIBERATE_DIFFERENCES = {
    # Queued analysis can wait, so it uses Bedrock's cheaper flex tier.
    ("AnalysisFunction", "BEDROCK_SERVICE_TIER"),
    # AWS serves the API over HTTPS only; a local run uses plain HTTP.
    ("ApiFunction", "SESSION_COOKIE_SECURE"),
}
# Values a stack parameter may allow beyond the ones it lists. CloudFormation
# takes any number between a Number parameter's bounds, fractions included,
# and any text a String parameter's pattern matches. These are every whole
# number and half from 0 to 100, a negative number, empty text and a word.
PARAMETER_PROBES = ("", "-1", "word", *(f"{half / 2:g}" for half in range(201)))


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


def parameter_variables_name_registered_secrets(model: TemplateModel) -> list[str]:
    """Each *_PARAMETER variable names its secret's parameter, as SECRETS registers it.

    A gated secret's variable is empty while its switch is off.
    """
    registered = {secret.variable: secret for secret in SECRETS}
    problems = []
    for function in model.functions().values():
        for name, value in function.environment.items():
            if not name.endswith("_PARAMETER"):
                continue
            secret = registered.get(name)
            if secret is None:
                problems.append(f"{function.logical_id}.{name} is not a registered secret")
                continue
            expected = f"${{ParameterPathPrefix}}/{secret.parameter}"
            if [parameter for parameter in possible_strings(value) if parameter] != [expected]:
                problems.append(f"{function.logical_id}.{name} does not name {expected}")
    return problems


def functions_read_only_the_secrets_they_name(model: TemplateModel) -> list[str]:
    """A function may read a registered secret only if its environment names it.

    The analysis worker reads untrusted PDFs, so it must not be able to read
    the Brevo key or the Reddit credentials it never uses.
    """
    return [
        f"{function.logical_id} may read {secret.parameter} but does not name {secret.variable}"
        for function in model.functions().values()
        for secret in SECRETS
        if secret.variable not in function.environment
        and function.can_read_parameter(f"${{ParameterPathPrefix}}/{secret.parameter}")
    ]


def registered_secrets_are_deployed(model: TemplateModel) -> list[str]:
    named = {name for function in model.functions().values() for name in function.environment}
    return [
        f"No function names {secret.variable}"
        for secret in SECRETS
        if secret.variable not in named
    ]


def _literal(value: Any) -> str | None:
    """A plain value as CloudFormation passes it, or None for an intrinsic function."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def template_literals_match_declared_defaults(model: TemplateModel) -> list[str]:
    """A setting's literal value is its declared default, unless the difference is deliberate.

    The document size limits and MAX_PDF_PAGES drifted when the template and
    the code each wrote a default out.
    """
    declared = declared_settings()
    problems = []
    for function in model.functions().values():
        for name, value in function.environment.items():
            literal = _literal(value)
            if name not in declared or literal is None:
                continue
            try:
                parsed = declared[name].parse(literal)
            except ValueError as error:
                problems.append(f"{function.logical_id}.{name} {error}")
                continue
            deliberate = (function.logical_id, name) in DELIBERATE_DIFFERENCES
            if parsed != declared[name].default and not deliberate:
                problems.append(
                    f"{function.logical_id}.{name} is {literal}, "
                    f"but the code defaults to {declared[name].default}"
                )
    return problems


def template_variables_are_declared(model: TemplateModel) -> list[str]:
    """Every function variable is a declared setting or names a registered secret."""
    known = {*declared_settings(), *(secret.variable for secret in SECRETS)}
    return [
        f"{function.logical_id}.{name} is not a declared setting"
        for function in model.functions().values()
        for name in function.environment
        if name not in known
    ]


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def template_parameters_fit_declared_limits(model: TemplateModel) -> list[str]:
    """Every value a stack parameter allows is one its setting accepts.

    Otherwise a value CloudFormation and the release plan accept would stop
    the function at its first settings read. The rule tries the parameter's
    default, allowed values and bounds, then each of PARAMETER_PROBES that
    ``Parameter.problems`` accepts, and reports the first value the setting
    refuses. The probes are a sample, not a proof. They catch a Number
    parameter feeding a whole-number setting, and a pattern that lets in a
    negative number or a whole number up to 100 that the setting refuses.
    """
    declared = declared_settings()
    parameters = model.parameter_definitions()
    fed = {
        (name, ref_target(value))
        for function in model.functions().values()
        for name, value in function.environment.items()
        if name in declared and ref_target(value) in parameters
    }
    problems = []
    for name, parameter_name in sorted(fed):
        parameter = parameters[parameter_name]
        listed = {*parameter.allowed_values}
        if parameter.default is not None:
            listed.add(parameter.default)
        listed.update(
            _number(bound)
            for bound in (parameter.min_value, parameter.max_value)
            if bound is not None
        )
        probed = {probe for probe in PARAMETER_PROBES if not parameter.problems(probe)}
        for allowed in [*sorted(listed), *sorted(probed - listed)]:
            try:
                declared[name].parse(allowed)
            except ValueError as error:
                problems.append(f"{parameter.name} allows {allowed!r}, but {name} {error}")
                break
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
    parameter_variables_name_registered_secrets,
    functions_read_only_the_secrets_they_name,
    registered_secrets_are_deployed,
    template_literals_match_declared_defaults,
    template_parameters_fit_declared_limits,
    template_variables_are_declared,
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


def _grant_every_parameter(document: dict, function_id: str) -> None:
    """Let a function read every parameter under the prefix, as the API may."""
    _properties(document, function_id)["Policies"][0]["Statement"].append(
        {
            "Effect": "Allow",
            "Action": "ssm:GetParameter",
            "Resource": {
                "Fn::Sub": "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}"
                ":parameter${ParameterPathPrefix}/*"
            },
        }
    )


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
    "unregistered parameter variable": (
        parameter_variables_name_registered_secrets,
        lambda d: _environment(d, "ApiFunction").update(
            GROQ_API_KEY_PARAMETER={"Fn::Sub": "${ParameterPathPrefix}/groq-api-key"}
        ),
    ),
    "parameter path drift": (
        parameter_variables_name_registered_secrets,
        lambda d: _environment(d, "ApiFunction").update(
            REDDIT_CLIENT_ID_PARAMETER={"Fn::Sub": "${ParameterPathPrefix}/reddit-id"}
        ),
    ),
    "wildcard parameter grant": (
        functions_read_only_the_secrets_they_name,
        lambda d: _grant_every_parameter(d, "AnalysisFunction"),
    ),
    "registered secret unused": (
        registered_secrets_are_deployed,
        lambda d: [
            _environment(d, function_id).pop("BREVO_API_KEY_PARAMETER")
            for function_id in ("ApiFunction", "NotificationFunction")
        ],
    ),
    "template default drifts": (
        template_literals_match_declared_defaults,
        lambda d: _environment(d, "ApiFunction").update(BEDROCK_MAX_PROMPT_CHARS="20000"),
    ),
    "parameter allows a rejected value": (
        template_parameters_fit_declared_limits,
        lambda d: d["Parameters"]["AlertMaxPerInvestorPerRun"].update(Default="0"),
    ),
    "number parameter allows a fraction": (
        template_parameters_fit_declared_limits,
        lambda d: d["Parameters"].update(
            PublicDiscussionPerSourceLimit={
                "Type": "Number",
                "Default": 10,
                "MinValue": 1,
                "MaxValue": 25,
            }
        ),
    ),
    "parameter pattern allows a rejected value": (
        template_parameters_fit_declared_limits,
        lambda d: d["Parameters"]["PublicDiscussionPerSourceLimit"].update(
            AllowedPattern="^[0-9]+$"
        ),
    ),
    "undeclared template variable": (
        template_variables_are_declared,
        lambda d: _environment(d, "DiscoveryFunction").update(UNUSED_LIMIT="1"),
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
# Staging verification reads the same model
# ---------------------------------------------------------------------------

class DeployedStack:
    """A fake AWS CLI for a stack deployed exactly as the template declares."""

    def __init__(self, model: TemplateModel) -> None:
        self.statuses = {logical_id: "UPDATE_COMPLETE" for logical_id in model.resources}
        self.outputs = {key: f"https://sqs.example/{key}" for key in model.outputs}
        self.attributes = {}
        for queue_id, queue in model.queues().items():
            [output] = model.outputs_referencing(queue_id)
            attributes = {
                "QueueArn": f"arn:aws:sqs:region:account:{queue_id}",
                "VisibilityTimeout": str(queue.visibility_timeout),
                "MessageRetentionPeriod": str(queue.retention),
            }
            if queue.dead_letter_queue:
                attributes["RedrivePolicy"] = (
                    f'{{"deadLetterTargetArn":"arn:aws:sqs:region:account:'
                    f'{queue.dead_letter_queue}","maxReceiveCount":"{queue.max_receive_count}"}}'
                )
            self.attributes[self.outputs[output]] = attributes

    def __call__(self, service: str, command: str, *args: str) -> dict:
        if command == "list-stack-resources":
            return {
                "StackResourceSummaries": [
                    {"LogicalResourceId": logical_id, "ResourceStatus": status}
                    for logical_id, status in self.statuses.items()
                ]
            }
        if command == "describe-stacks":
            outputs = [{"OutputKey": k, "OutputValue": v} for k, v in self.outputs.items()]
            return {"Stacks": [{"Outputs": outputs}]}
        assert (service, command) == ("sqs", "get-queue-attributes")
        return {"Attributes": self.attributes[args[args.index("--queue-url") + 1]]}


def _verify(stack: DeployedStack) -> list[str]:
    problems, _summary = verify_queue_wiring.verify(template_model(), stack, "stack")
    return problems


def test_staging_verification_checks_every_queue_from_the_model() -> None:
    model = template_model()
    resources = verify_queue_wiring.pipeline_resources(model)

    assert set(model.queues()) | {"AnalysisQueuePolicy", "RawDocumentBucket"} <= set(resources)
    assert {"NotificationFunction", "SchedulerFunction", "NotificationDlqAlarm"} <= set(resources)
    assert "FrontendBucket" not in resources
    assert [expected.queue for expected in verify_queue_wiring.queue_expectations(model)] == [
        "AnalysisQueue",
        "DiscoveryQueue",
        "DownloadQueue",
        "NotificationQueue",
    ]
    assert _verify(DeployedStack(model)) == []


def test_staging_verification_reports_drift() -> None:
    stack = DeployedStack(template_model())
    stack.statuses.pop("DownloadDlqAlarm")
    stack.statuses["AnalysisFunction"] = "UPDATE_ROLLBACK_COMPLETE"
    stack.outputs["NotificationDeadLetterQueueUrl"] = ""
    stack.attributes[stack.outputs["AnalysisQueueUrl"]]["VisibilityTimeout"] = "30"
    stack.attributes[stack.outputs["DiscoveryQueueUrl"]]["RedrivePolicy"] = (
        '{"deadLetterTargetArn":"arn:aws:sqs:region:account:Other","maxReceiveCount":"3"}'
    )

    assert sorted(_verify(stack)) == [
        "AnalysisFunction is in unhealthy state: UPDATE_ROLLBACK_COMPLETE",
        "AnalysisQueue: visibility timeout is not 4320s",
        "DiscoveryQueue: maxReceiveCount is not 5",
        "DiscoveryQueue: redrive does not target its dead-letter queue",
        "DownloadDlqAlarm is missing from stack",
        "Stack output NotificationDeadLetterQueueUrl is missing or empty",
    ]


def test_staging_workflow_runs_the_model_based_verification() -> None:
    workflow = STAGING_VERIFICATION_WORKFLOW.read_text(encoding="utf-8")

    assert "python -m tools.verify_queue_wiring" in workflow
    assert "PyYAML==" in workflow


# ---------------------------------------------------------------------------
# CI
# ---------------------------------------------------------------------------

def test_queue_ci_lints_every_template_and_runs_when_one_changes() -> None:
    """A template the job does not lint, or a file it does not watch, goes unchecked.

    The job runs when an infrastructure template, one of its test files or
    the staging verification workflow those tests read changes.
    """
    workflow = yaml.safe_load(QUEUE_CI_WORKFLOW.read_text(encoding="utf-8"))
    templates = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (REPOSITORY_ROOT / "infra").glob("*.yaml")
    }
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    [lint] = [step["run"].split() for step in steps if step.get("run", "").startswith("cfn-lint")]
    [tests] = [step["run"] for step in steps if "python -m pytest" in step.get("run", "")]
    # PyYAML reads the "on" key as True.
    push, pull_request = (workflow[True][event]["paths"] for event in ("push", "pull_request"))

    assert set(lint[1:]) == templates
    assert push == pull_request
    assert templates <= set(push)
    assert {f"backend/{test}" for test in re.findall(r"tests/\w+\.py", tests)} <= set(push)
    assert ".github/workflows/verify-staging-queue-wiring.yml" in push


def test_queue_ci_imports_the_configuration_with_the_standard_library_alone() -> None:
    """This file reads SECRETS from app.core.config in a job without the backend's packages.

    The import runs with no site-packages at all, and the job must run when
    any module it loads changes.
    """
    backend = REPOSITORY_ROOT / "backend"
    loaded = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import sys, app.core.config; "
            "print(*sorted(name for name in sys.modules if name.split('.')[0] == 'app'))",
        ],
        cwd=backend,
        capture_output=True,
        text=True,
        check=True,
    )
    workflow = yaml.safe_load(QUEUE_CI_WORKFLOW.read_text(encoding="utf-8"))

    def source(module: str) -> str:
        path = backend.joinpath(*module.split("."))
        path = path / "__init__.py" if path.is_dir() else path.with_suffix(".py")
        return path.relative_to(REPOSITORY_ROOT).as_posix()

    assert {source(module) for module in loaded.stdout.split()} <= set(
        workflow[True]["push"]["paths"]
    )
