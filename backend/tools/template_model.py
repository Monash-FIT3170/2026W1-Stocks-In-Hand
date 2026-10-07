"""infra/template.yaml as data: parse it once and answer questions about it.

Contract tests check rules against this model instead of slicing the
template text, which depends on resource order and can match a value from
the next resource. The staging queue verification (``tools.verify_queue_wiring``)
reads the same model, so the deployed stack is compared with what the
template declares rather than with a hand-kept list.

Intrinsic functions keep CloudFormation's JSON form: ``!Ref X`` becomes
``{"Ref": "X"}``, ``!GetAtt X.Arn`` becomes ``{"Fn::GetAtt": ["X", "Arn"]}``
and ``!Sub s`` becomes ``{"Fn::Sub": "s"}``.

Only the standard library and PyYAML are used: the queue-wiring CI job runs
the tests that import this with just pytest and PyYAML installed.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPOSITORY_ROOT / "infra" / "template.yaml"

# SQS defaults that apply when a queue does not set the property.
DEFAULT_VISIBILITY_TIMEOUT = 30
DEFAULT_MESSAGE_RETENTION = 345600
# Lambda's default timeout when a function does not set one.
DEFAULT_FUNCTION_TIMEOUT = 3


class CloudFormationLoader(yaml.SafeLoader):
    """Load CloudFormation YAML, keeping intrinsic functions as data."""


def _construct_intrinsic(loader: CloudFormationLoader, tag_suffix: str, node: yaml.Node) -> dict:
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    if tag_suffix == "Ref":
        return {"Ref": value}
    if tag_suffix == "Condition":
        return {"Condition": value}
    if tag_suffix == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {f"Fn::{tag_suffix}": value}


CloudFormationLoader.add_multi_constructor("!", _construct_intrinsic)


def parse_template(text: str) -> dict:
    return yaml.load(text, Loader=CloudFormationLoader)


def ref_target(value: Any) -> str | None:
    """The logical ID behind ``!Ref X``, or None."""
    if isinstance(value, dict) and set(value) == {"Ref"}:
        return value["Ref"]
    return None


def getatt_target(value: Any, attribute: str) -> str | None:
    """The logical ID behind ``!GetAtt X.<attribute>``, or None."""
    if isinstance(value, dict) and set(value) == {"Fn::GetAtt"}:
        logical_id, name = value["Fn::GetAtt"]
        if name == attribute:
            return logical_id
    return None


def branches(value: Any) -> Iterator[Any]:
    """Every value ``value`` can take, looking through ``!If`` and skipping NoValue."""
    if isinstance(value, dict) and set(value) == {"Fn::If"}:
        _condition, when_true, when_false = value["Fn::If"]
        yield from branches(when_true)
        yield from branches(when_false)
    elif ref_target(value) != "AWS::NoValue":
        yield value


def possible_strings(value: Any) -> list[str]:
    """The literal or ``!Sub`` strings a value can resolve to."""
    strings = []
    for branch in branches(value):
        if isinstance(branch, str):
            strings.append(branch)
        elif isinstance(branch, dict) and set(branch) == {"Fn::Sub"}:
            template = branch["Fn::Sub"]
            strings.append(template if isinstance(template, str) else template[0])
    return strings


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else [value]


@dataclass(frozen=True)
class Statement:
    """One IAM policy statement, with the condition it is granted under."""

    sid: str | None
    actions: tuple[str, ...]
    resources: tuple[Any, ...]
    condition: str | None

    def allows(self, action: str) -> bool:
        return any(fnmatch.fnmatchcase(action, granted) for granted in self.actions)


@dataclass(frozen=True)
class Queue:
    logical_id: str
    properties: dict

    @property
    def visibility_timeout(self) -> int:
        return int(self.properties.get("VisibilityTimeout", DEFAULT_VISIBILITY_TIMEOUT))

    @property
    def retention(self) -> int:
        return int(self.properties.get("MessageRetentionPeriod", DEFAULT_MESSAGE_RETENTION))

    @property
    def encrypted(self) -> bool:
        return self.properties.get("SqsManagedSseEnabled") is True or (
            "KmsMasterKeyId" in self.properties
        )

    @property
    def dead_letter_queue(self) -> str | None:
        redrive = self.properties.get("RedrivePolicy") or {}
        return getatt_target(redrive.get("deadLetterTargetArn"), "Arn")

    @property
    def max_receive_count(self) -> int | None:
        redrive = self.properties.get("RedrivePolicy") or {}
        count = redrive.get("maxReceiveCount")
        return None if count is None else int(count)


@dataclass(frozen=True)
class Function:
    logical_id: str
    properties: dict

    @property
    def timeout(self) -> int:
        return int(self.properties.get("Timeout", DEFAULT_FUNCTION_TIMEOUT))

    @property
    def environment(self) -> dict[str, Any]:
        return (self.properties.get("Environment") or {}).get("Variables") or {}

    @property
    def sqs_events(self) -> dict[str, dict]:
        """Event name to properties for every SQS event source."""
        return {
            name: event.get("Properties") or {}
            for name, event in (self.properties.get("Events") or {}).items()
            if event.get("Type") == "SQS"
        }

    @property
    def consumed_queues(self) -> list[str]:
        return [
            queue
            for event in self.sqs_events.values()
            if (queue := getatt_target(event.get("Queue"), "Arn")) is not None
        ]

    @property
    def statements(self) -> list[Statement]:
        """Inline policy statements, including ones granted under ``!If``."""
        found = []
        for policy in self.properties.get("Policies") or []:
            condition = None
            if isinstance(policy, dict) and set(policy) == {"Fn::If"}:
                condition = policy["Fn::If"][0]
            for document in branches(policy):
                if not isinstance(document, dict):
                    continue
                for statement in document.get("Statement") or []:
                    if statement.get("Effect", "Allow") != "Allow":
                        continue
                    found.append(
                        Statement(
                            sid=statement.get("Sid"),
                            actions=tuple(_as_list(statement.get("Action", []))),
                            resources=tuple(_as_list(statement.get("Resource", []))),
                            condition=condition,
                        )
                    )
        return found

    @property
    def send_message_targets(self) -> set[str]:
        """Queues this function may send to."""
        return {
            queue
            for statement in self.statements
            if statement.allows("sqs:SendMessage")
            for resource in statement.resources
            if (queue := getatt_target(resource, "Arn")) is not None
        }

    @property
    def readable_parameter_patterns(self) -> list[str]:
        """SSM parameter names this function may read, as patterns.

        For example ``${ParameterPathPrefix}/database-url`` or
        ``${ParameterPathPrefix}/*``.
        """
        patterns = []
        for statement in self.statements:
            if not statement.allows("ssm:GetParameter"):
                continue
            for resource in statement.resources:
                for arn in possible_strings(resource):
                    _, separator, name = arn.strip().partition(":parameter")
                    if separator:
                        patterns.append(name)
        return patterns

    def can_read_parameter(self, name: str) -> bool:
        return any(
            fnmatch.fnmatchcase(name, pattern)
            for pattern in self.readable_parameter_patterns
        )


class TemplateModel:
    """Questions about one parsed template."""

    def __init__(self, document: dict) -> None:
        self.document = document

    @property
    def parameters(self) -> dict[str, dict]:
        return self.document.get("Parameters") or {}

    @property
    def resources(self) -> dict[str, dict]:
        return self.document.get("Resources") or {}

    @property
    def outputs(self) -> dict[str, dict]:
        return self.document.get("Outputs") or {}

    def resource(self, logical_id: str) -> dict:
        try:
            return self.resources[logical_id]
        except KeyError:
            raise KeyError(f"Resource '{logical_id}' not found in the template") from None

    def properties(self, logical_id: str) -> dict:
        return self.resource(logical_id).get("Properties") or {}

    def of_type(self, resource_type: str) -> dict[str, dict]:
        return {
            logical_id: resource
            for logical_id, resource in self.resources.items()
            if resource.get("Type") == resource_type
        }

    def functions(self) -> dict[str, Function]:
        return {
            logical_id: Function(logical_id, resource.get("Properties") or {})
            for logical_id, resource in self.of_type("AWS::Serverless::Function").items()
        }

    def function(self, logical_id: str) -> Function:
        return Function(logical_id, self.properties(logical_id))

    def image_functions(self) -> list[str]:
        """Logical IDs of every Lambda deployed from a container image."""
        return sorted(
            logical_id
            for logical_id, function in self.functions().items()
            if function.properties.get("PackageType") == "Image"
        )

    def queues(self) -> dict[str, Queue]:
        return {
            logical_id: Queue(logical_id, resource.get("Properties") or {})
            for logical_id, resource in self.of_type("AWS::SQS::Queue").items()
        }

    def queue(self, logical_id: str) -> Queue:
        return Queue(logical_id, self.properties(logical_id))

    def consumers(self) -> dict[str, list[str]]:
        """Queue logical ID to the functions that consume it."""
        consumers: dict[str, list[str]] = {}
        for function in self.functions().values():
            for queue in function.consumed_queues:
                consumers.setdefault(queue, []).append(function.logical_id)
        return consumers

    def dead_letter_queues(self) -> set[str]:
        return {
            queue.dead_letter_queue
            for queue in self.queues().values()
            if queue.dead_letter_queue is not None
        }

    def alarms_watching(self, queue_id: str) -> list[str]:
        """CloudWatch alarms whose QueueName dimension is this queue."""
        return [
            logical_id
            for logical_id, resource in self.of_type("AWS::CloudWatch::Alarm").items()
            if any(
                getatt_target(dimension.get("Value"), "QueueName") == queue_id
                for dimension in (resource.get("Properties") or {}).get("Dimensions") or []
            )
        ]

    def outputs_referencing(self, logical_id: str) -> list[str]:
        """Outputs whose value is ``!Ref logical_id``."""
        return [
            key
            for key, output in self.outputs.items()
            if ref_target(output.get("Value")) == logical_id
        ]

    def bucket_queue_notifications(self, bucket_id: str) -> list[dict]:
        configuration = self.properties(bucket_id).get("NotificationConfiguration") or {}
        return configuration.get("QueueConfigurations") or []


@lru_cache(maxsize=None)
def _load(path: Path) -> dict:
    return parse_template(path.read_text(encoding="utf-8"))


def template_model(path: Path = TEMPLATE_PATH) -> TemplateModel:
    """The checked-in template, parsed once per process."""
    return TemplateModel(_load(path))
