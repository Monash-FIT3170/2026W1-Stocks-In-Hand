"""infra/template.yaml as data: parse it once and answer questions about it.

Contract tests check rules against this model instead of slicing the
template text, which depends on resource order and can match a value from
the next resource. The staging queue verification (``tools.verify_queue_wiring``)
reads the same model, so the deployed stack is compared with what the
template declares rather than with a hand-kept list. The release module
(``tools.release``) checks parameter values against its constraints and rules,
and the deploy role tests read infra/github-oidc.yaml through the same model
to check what each role may do.

Intrinsic functions keep CloudFormation's JSON form: ``!Ref X`` becomes
``{"Ref": "X"}``, ``!GetAtt X.Arn`` becomes ``{"Fn::GetAtt": ["X", "Arn"]}``
and ``!Sub s`` becomes ``{"Fn::Sub": "s"}``.

Only the standard library and PyYAML are used: the queue-wiring CI job runs
the tests that import this with just pytest and PyYAML installed.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterator, Mapping
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
    return yaml.load(text, Loader=CloudFormationLoader)  # nosec B506 - CloudFormationLoader is a SafeLoader


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


def _intrinsic(value: Any) -> str | None:
    """The intrinsic function ``value`` calls, such as ``Fn::If`` or ``Ref``, or None."""
    if isinstance(value, dict) and len(value) == 1:
        [name] = value
        if name in ("Ref", "Condition") or str(name).startswith("Fn::"):
            return name
    return None


def _outcomes(value: Any) -> Iterator[Any]:
    """Every value ``value`` can take, looking through ``!If`` and keeping NoValue."""
    if isinstance(value, dict) and set(value) == {"Fn::If"}:
        _condition, when_true, when_false = value["Fn::If"]
        yield from _outcomes(when_true)
        yield from _outcomes(when_false)
    else:
        yield value


def branches(value: Any) -> Iterator[Any]:
    """Every value ``value`` can take, looking through ``!If`` and skipping NoValue."""
    for outcome in _outcomes(value):
        if ref_target(outcome) != "AWS::NoValue":
            yield outcome


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


def substitute(template: str, values: Mapping[str, str]) -> str:
    """Fill the ``${Name}`` references of a ``!Sub`` string from ``values``."""

    def value(reference: re.Match[str]) -> str:
        name = reference.group(1)
        if name not in values:
            raise KeyError(f"No value for ${{{name}}} in {template!r}")
        return values[name]

    return re.sub(r"\$\{([^}!][^}]*)\}", value, template)


def _filled(value: Any, values: Mapping[str, str]) -> str:
    """A literal, ``!Sub``, ``!Ref`` or ``!GetAtt`` value as text, filled in from ``values``.

    ``!Ref X`` and ``!GetAtt X.Attribute`` look up ``X`` and ``X.Attribute``,
    as ``${X}`` and ``${X.Attribute}`` do in a ``!Sub``.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and set(value) == {"Fn::Sub"} and isinstance(value["Fn::Sub"], str):
        return substitute(value["Fn::Sub"], values)
    name = ref_target(value)
    if name is None and isinstance(value, dict) and set(value) == {"Fn::GetAtt"}:
        name = ".".join(value["Fn::GetAtt"])
    if name is None:
        raise ValueError(f"Cannot fill in {value!r}")
    return substitute(f"${{{name}}}", values)


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str:
    """A YAML scalar as CloudFormation reads it: ``10`` is "10", ``true`` is "true"."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True)
class Parameter:
    """One template parameter and the constraints CloudFormation checks a value against."""

    name: str
    type: str
    default: str | None
    allowed_values: tuple[str, ...]
    allowed_pattern: str | None
    min_value: float | None
    max_value: float | None

    def problems(self, value: str) -> list[str]:
        """Why CloudFormation would refuse ``value`` for this parameter, if it would."""
        problems = []
        if self.allowed_values and value not in self.allowed_values:
            problems.append(
                f"{self.name} must be one of {', '.join(self.allowed_values)}, not {value!r}"
            )
        if self.allowed_pattern is not None and not re.fullmatch(self.allowed_pattern, value):
            problems.append(f"{self.name} {value!r} does not match {self.allowed_pattern}")
        if self.type == "Number":
            try:
                number = float(value)
            except ValueError:
                problems.append(f"{self.name} must be a number, not {value!r}")
            else:
                if self.min_value is not None and number < self.min_value:
                    problems.append(f"{self.name} must be at least {self.min_value:g}, not {value}")
                if self.max_value is not None and number > self.max_value:
                    problems.append(f"{self.name} must be at most {self.max_value:g}, not {value}")
        return problems


@dataclass(frozen=True)
class Statement:
    """One IAM policy statement that allows something.

    ``condition`` is the template condition it is granted under, if any, and
    ``iam_condition`` its own IAM Condition block, such as
    ``{"ArnEquals": {"cloudformation:RoleArn": ...}}``.
    """

    sid: str | None
    actions: tuple[str, ...]
    resources: tuple[Any, ...]
    condition: str | None
    iam_condition: Mapping[str, Any]

    def allows(self, action: str) -> bool:
        """Whether this statement names ``action``, matching it as IAM does.

        IAM ignores case in an action, so ``ecr:batchdeleteimage`` grants
        ecr:BatchDeleteImage, and ``*`` and ``?`` are its wildcards.
        """
        return any(
            fnmatch.fnmatchcase(action.lower(), granted.lower()) for granted in self.actions
        )

    def covers(self, action: str, arn: str, values: Mapping[str, str]) -> bool:
        """Whether this statement allows ``action`` on the resource ``arn``.

        Each resource is filled in from ``values`` first: ``${Name}``, ``!Ref
        Name`` and ``!GetAtt Name.Attribute`` all look their name up there, so
        ``values`` holds the pseudo parameters, such as ``AWS::AccountId``, as
        well as parameter values. IAM's ``*`` and ``?`` wildcards then match
        ``arn``. The IAM condition is not checked: read ``iam_condition``.

        When the answer depends on a template condition, through a resource
        under ``!If`` or a statement granted under one, ValueError says so
        rather than guessing.
        """
        if not self.allows(action):
            return False
        answers = [
            {
                ref_target(outcome) != "AWS::NoValue"
                and fnmatch.fnmatchcase(arn, _filled(outcome, values))
                for outcome in _outcomes(resource)
            }
            for resource in self.resources
        ]
        if not any(True in answer for answer in answers):
            return False
        if self.condition is None and {True} in answers:
            return True
        raise ValueError(
            f"Whether {self.sid or 'a statement'} allows {action} on {arn} depends on "
            f"{self.condition or 'a template condition'}"
        )


def _readable(value: Any, what: str) -> Any:
    """``value`` itself, or ValueError when it is an intrinsic function."""
    function = _intrinsic(value)
    if function is not None:
        raise ValueError(f"{what} is {function}, which the model cannot read")
    return value


def _statement(statement: Any, condition: str | None) -> Statement:
    """One policy statement, or ValueError when the model cannot say what it grants."""
    if not isinstance(statement, dict) or _intrinsic(statement) is not None:
        raise ValueError(f"A policy statement is not one the model can read: {statement!r}")
    name = statement.get("Sid") or "A statement"
    effect = statement.get("Effect", "Allow")
    if effect == "Deny":
        raise ValueError(f"{name} is a Deny, which the model does not weigh against the grants")
    if effect != "Allow":
        raise ValueError(f"{name} has Effect {effect!r}, which the model cannot read")
    inverted = sorted({"NotAction", "NotResource"} & set(statement))
    if inverted:
        raise ValueError(f"{name} uses {' and '.join(inverted)}, which the model cannot read")
    actions = tuple(_as_list(statement.get("Action", [])))
    if not all(isinstance(action, str) for action in actions):
        raise ValueError(f"{name} has an Action the model cannot read: {statement['Action']!r}")
    return Statement(
        sid=statement.get("Sid"),
        actions=actions,
        resources=tuple(_as_list(statement.get("Resource", []))),
        condition=condition,
        iam_condition=statement.get("Condition") or {},
    )


def _policy_statements(policies: Any, document_key: str | None) -> list[Statement]:
    """The statements of a resource's inline policies, including ones granted under ``!If``.

    An IAM role keeps each policy's document under ``document_key``
    (PolicyDocument). A SAM function lists the documents themselves, with
    ``document_key`` None, beside managed policy names and SAM policy
    templates, which are skipped.

    What would make the statements grant more or less than they say raises
    ValueError instead of being read as granting nothing: a Deny statement,
    which the model does not weigh against the grants, NotAction or
    NotResource, an Effect other than Allow, an Action that is not a list of
    names, and an intrinsic function where the policies, a document, its
    Statement block or one statement should be. ``!If`` is read only around
    a whole policy and in a Resource (see ``Statement.covers``).
    """
    found: list[Statement] = []
    for policy in _as_list(_readable(policies or [], "Policies")):
        condition = None
        if isinstance(policy, dict) and set(policy) == {"Fn::If"}:
            condition = policy["Fn::If"][0]
        for branch in branches(policy):
            document: Any
            if document_key is None:
                if not (isinstance(branch, dict) and "Statement" in branch):
                    continue  # A managed policy name or a SAM policy template.
                document = branch
            else:
                document = branch.get(document_key) if isinstance(branch, dict) else None
                if not isinstance(document, dict) or _intrinsic(document) is not None:
                    raise ValueError(
                        f"A policy's {document_key} is not one the model can read: {document!r}"
                    )
            statements = _readable(document.get("Statement") or [], "A policy's Statement")
            found.extend(_statement(statement, condition) for statement in _as_list(statements))
    return found


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
    def image_parameter(self) -> str | None:
        """The parameter behind ``ImageUri: !Ref X``, for a function deployed from an image."""
        return ref_target(self.properties.get("ImageUri"))

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
        return _policy_statements(self.properties.get("Policies"), None)

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

    @property
    def conditions(self) -> dict[str, Any]:
        return self.document.get("Conditions") or {}

    def parameter_definitions(self) -> dict[str, Parameter]:
        """Every parameter with its default and constraints, in template order."""
        return {
            name: Parameter(
                name=name,
                type=definition.get("Type", "String"),
                default=_text(definition["Default"]) if "Default" in definition else None,
                allowed_values=tuple(
                    _text(value) for value in definition.get("AllowedValues") or []
                ),
                allowed_pattern=definition.get("AllowedPattern"),
                min_value=_number(definition.get("MinValue")),
                max_value=_number(definition.get("MaxValue")),
            )
            for name, definition in self.parameters.items()
        }

    def rule_failures(self, values: Mapping[str, str]) -> list[str]:
        """The AssertDescription of every rule assertion these parameter values fail.

        CloudFormation checks the Rules section before it creates a change set.
        Fn::Equals, Fn::Not, Fn::And, Fn::Or, Ref and Condition are understood.
        Anything else raises ValueError, even in a rule that does not apply to
        these values, so a new kind of rule cannot pass unchecked.
        """
        failures = []
        for name, rule in (self.document.get("Rules") or {}).items():
            condition = rule.get("RuleCondition")
            applies = condition is None or self._holds(condition, values)
            for assertion in rule.get("Assertions") or []:
                if not self._holds(assertion["Assert"], values) and applies:
                    failures.append(assertion.get("AssertDescription") or f"Rule {name} failed")
        return failures

    def _holds(self, expression: Any, values: Mapping[str, str]) -> bool:
        if isinstance(expression, dict) and len(expression) == 1:
            [(function, argument)] = expression.items()
            if function == "Fn::Equals":
                left, right = argument
                return self._operand(left, values) == self._operand(right, values)
            if function == "Fn::Not":
                [negated] = argument
                return not self._holds(negated, values)
            # Every branch is evaluated, so an unsupported intrinsic always raises.
            if function == "Fn::And":
                return all([self._holds(branch, values) for branch in argument])
            if function == "Fn::Or":
                return any([self._holds(branch, values) for branch in argument])
            if function == "Condition":
                return self._holds(self.conditions[argument], values)
        raise ValueError(f"Cannot evaluate {expression!r}")

    @staticmethod
    def _operand(value: Any, values: Mapping[str, str]) -> str:
        parameter = ref_target(value)
        if parameter is not None:
            return values[parameter]
        if isinstance(value, (str, int, float)):
            return _text(value)
        raise ValueError(f"Cannot evaluate {value!r}")

    def gated_secrets(self) -> dict[str, str]:
        """SSM parameter names a function reads only while a switch is on, and that switch.

        A ``*_PARAMETER`` variable is gated when it is ``!If [condition, !Sub
        name, ""]`` and the condition is ``!Equals [!Ref Switch, "true"]``. The
        name keeps its references, for example ``${ParameterPathPrefix}/brevo-api-key``.
        Any other ``!If`` raises ValueError rather than leaving a secret out.
        """
        secrets: dict[str, str] = {}
        for function in self.functions().values():
            for variable, value in function.environment.items():
                if not (
                    variable.endswith("_PARAMETER")
                    and isinstance(value, dict)
                    and set(value) == {"Fn::If"}
                ):
                    continue
                condition, when_on, when_off = value["Fn::If"]
                switch = self._switch(condition)
                names = possible_strings(when_on)
                if switch is None or when_off != "" or len(names) != 1:
                    raise ValueError(
                        f"{function.logical_id}.{variable} is not a secret behind one switch"
                    )
                [name] = names
                if secrets.get(name, switch) != switch:
                    raise ValueError(f"{name} is behind two different switches")
                secrets[name] = switch
        return secrets

    def _switch(self, condition: str) -> str | None:
        """The parameter X when the condition is ``!Equals [!Ref X, "true"]``."""
        expression = self.conditions.get(condition)
        if not (isinstance(expression, dict) and set(expression) == {"Fn::Equals"}):
            return None
        left, right = expression["Fn::Equals"]
        if right == "true":
            return ref_target(left)
        if left == "true":
            return ref_target(right)
        return None

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

    def role_statements(self, logical_id: str) -> list[Statement]:
        """The statements of an IAM role's inline policies, including ones under ``!If``.

        A managed policy grants more than these say and a permissions boundary
        can take grants away, so a role with ManagedPolicyArns or a
        PermissionsBoundary raises ValueError rather than leave either out, as
        does a policy the model cannot read. A separate policy resource that
        names the role is not read.
        """
        properties = self.properties(logical_id)
        if properties.get("ManagedPolicyArns"):
            raise ValueError(f"{logical_id} has managed policies, which the model cannot read")
        if properties.get("PermissionsBoundary"):
            raise ValueError(
                f"{logical_id} has a permissions boundary, which the model cannot read"
            )
        return _policy_statements(properties.get("Policies"), "PolicyDocument")

    def image_functions(self) -> list[str]:
        """Logical IDs of every Lambda deployed from a container image."""
        return sorted(
            logical_id
            for logical_id, function in self.functions().items()
            if function.properties.get("PackageType") == "Image"
        )

    def image_parameters(self) -> dict[str, list[str]]:
        """Each ``ImageUri`` parameter and the image functions deployed from it."""
        functions = self.functions()
        image_parameters: dict[str, list[str]] = {}
        for logical_id in self.image_functions():
            parameter = functions[logical_id].image_parameter
            if parameter is not None:
                image_parameters.setdefault(parameter, []).append(logical_id)
        return image_parameters

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
