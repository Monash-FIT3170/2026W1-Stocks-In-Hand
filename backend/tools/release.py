"""Plan and apply a deploy of infra/template.yaml from one place.

``plan`` works out a value for every template parameter, checks each one
against the template's constraints and rules before anything is built, and
writes the plan to a file. ``apply`` runs the one ``sam deploy`` command the
plan describes. This is the only place that knows how a deploy is put
together: the parameters, the image repositories and the checks.

A parameter's value comes from the first of:

1. ``--set K=V``, even when V is empty;
2. ``--set-unless-empty K=V``, when V is not empty;
3. the live stack;
4. the template default.

The image parameters always point at the release SHA in this account's ECR
repositories. A release (not a rollback) also works out FrontendBaseUrl,
unless it is set.

    python -m tools.release plan --stack-name S --region R --release-sha SHA \\
        (--execute | --no-execute) [--rollback] [--no-execution-role] \\
        [--set K=V]... [--set-unless-empty K=V]... --out plan.json
    python -m tools.release apply plan.json [--dry-run]
    python -m tools.release outputs --stack-name S --region R \\
        [--github-env | --shell] Key[=NAME]...
    python -m tools.release previous-release --stack-name S --region R

Every AWS call goes through the ``Aws`` port and only reads; the one change
is the ``sam deploy`` that ``apply`` runs. Only the standard library and
PyYAML are used: the queue-wiring CI job runs the tests with just pytest and
PyYAML installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from tools.template_model import TEMPLATE_PATH, TemplateModel, substitute, template_model

# The ECR repository each image parameter's images are pushed to (infra/bootstrap.yaml).
IMAGE_REPOSITORIES = {
    "ApiImageUri": "stocks-in-hand-api",
    "ScraperImageUri": "stocks-in-hand-scraper",
    "AnalysisImageUri": "stocks-in-hand-analysis",
}
# The role CloudFormation applies a change set as (infra/github-oidc.yaml).
CLOUDFORMATION_ROLE_NAME = "stocks-in-hand-cloudformation-execution"
# sam deploy needs an S3 bucket for a larger template, and the GitHub deploy
# role has no grant for one.
INLINE_TEMPLATE_LIMIT = 51200

FULL_SHA = re.compile(r"[0-9a-f]{40}")

# Runs a command without a shell and returns its exit code.
Run = Callable[[list[str]], int]


class ReleaseError(Exception):
    """A deploy that must not go ahead, with every problem found."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True)
class LiveStack:
    """A deployed stack: its status, parameter values and outputs."""

    status: str
    parameters: dict[str, str]
    outputs: dict[str, str]


class Aws(Protocol):
    """The AWS reads a deploy needs. None of them changes anything."""

    def account_id(self) -> str: ...

    def stack(self, name: str) -> LiveStack | None:
        """The stack, or None when it does not exist or is still REVIEW_IN_PROGRESS."""

    def image_exists(self, repository: str, tag: str) -> bool: ...

    def parameter_type(self, name: str) -> str | None:
        """An SSM parameter's type, read from its metadata without decrypting it."""


def _executable(name: str) -> str:
    # On Windows sam is sam.cmd, which subprocess does not find by its bare name.
    executable = shutil.which(name)
    if executable is None:
        raise ReleaseError([f"{name} is not installed or not on PATH"])
    return executable


def _capture(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command without a shell and keep what it prints."""
    return subprocess.run(  # nosec B603 - fixed argv, no shell
        [_executable(command[0]), *command[1:]], capture_output=True, text=True, check=False
    )


def _stream(command: list[str]) -> int:
    """Run a command without a shell, letting it print as it goes."""
    return subprocess.run(  # nosec B603 - fixed argv, no shell
        [_executable(command[0]), *command[1:]], check=False
    ).returncode


class AwsCli:
    """The Aws port through the AWS CLI and whatever credentials it finds."""

    def __init__(
        self,
        region: str,
        run: Callable[[list[str]], subprocess.CompletedProcess[str]] = _capture,
    ) -> None:
        self.region = region
        self._run = run

    def account_id(self) -> str:
        return self._json(self._call("sts", "get-caller-identity"))["Account"]

    def stack(self, name: str) -> LiveStack | None:
        completed = self._call("cloudformation", "describe-stacks", "--stack-name", name)
        # SAM CLI tells a missing stack apart by the same text.
        if completed.returncode and f"Stack with id {name} does not exist" in completed.stderr:
            return None
        [stack] = self._json(completed)["Stacks"]
        # CreateChangeSet for a new stack leaves it REVIEW_IN_PROGRESS with
        # nothing deployed. SAM CLI creates such a stack, so it counts as new.
        if stack["StackStatus"] == "REVIEW_IN_PROGRESS":
            return None
        return LiveStack(
            status=stack["StackStatus"],
            parameters={
                parameter["ParameterKey"]: parameter.get("ParameterValue", "")
                for parameter in stack.get("Parameters") or []
            },
            outputs={
                output["OutputKey"]: output.get("OutputValue", "")
                for output in stack.get("Outputs") or []
            },
        )

    def image_exists(self, repository: str, tag: str) -> bool:
        completed = self._call(
            "ecr",
            "describe-images",
            "--repository-name",
            repository,
            "--image-ids",
            f"imageTag={tag}",
        )
        if completed.returncode and "ImageNotFoundException" in completed.stderr:
            return False
        self._json(completed)
        return True

    def parameter_type(self, name: str) -> str | None:
        completed = self._call("ssm", "get-parameter", "--name", name, "--query", "Parameter.Type")
        if completed.returncode and "ParameterNotFound" in completed.stderr:
            return None
        return self._json(completed)

    def _call(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self._run(["aws", *args, "--region", self.region, "--output", "json"])

    @staticmethod
    def _json(completed: subprocess.CompletedProcess[str]) -> Any:
        if completed.returncode:
            command = " ".join(completed.args[1:3])
            raise ReleaseError([f"aws {command} failed: {completed.stderr.strip()}"])
        return json.loads(completed.stdout)


@dataclass(frozen=True)
class Value:
    """A parameter value and where it came from: set, live, default, derived or image."""

    value: str
    source: str


@dataclass(frozen=True)
class ReleasePlan:
    """One checked sam deploy: written by ``plan``, run by ``apply``."""

    stack_name: str
    region: str
    release_sha: str
    registry: str
    role_arn: str | None
    execute: bool
    rollback: bool
    template: str
    template_sha256: str
    stack_status: str | None
    previous_release_sha: str | None
    # Every template parameter, in template order.
    parameters: dict[str, Value]
    live_parameters: dict[str, str]
    # Every image function and the repository its image is pulled from.
    image_repositories: dict[str, str]
    warnings: list[str]

    def sam_deploy_command(self) -> list[str]:
        command = [
            "sam",
            "deploy",
            "--template-file",
            self.template,
            "--stack-name",
            self.stack_name,
            "--region",
            self.region,
            "--capabilities",
            "CAPABILITY_IAM",
        ]
        if self.role_arn is not None:
            command += ["--role-arn", self.role_arn]
        for function, repository in self.image_repositories.items():
            command += ["--image-repositories", f"{function}={repository}"]
        command += ["--no-confirm-changeset", "--no-fail-on-empty-changeset"]
        if not self.execute:
            command.append("--no-execute-changeset")
        command.append("--parameter-overrides")
        command += [f"{name}={_quoted(value.value)}" for name, value in self.parameters.items()]
        return command

    def summary(self) -> list[str]:
        """The plan as Markdown: each value, where it came from and what it replaces."""
        if self.stack_status is None:
            live = "none yet, so this creates it"
        else:
            live = f"{self.stack_status}, running `{self.previous_release_sha or 'unknown'}`"
        lines = [
            f"### {'Rollback' if self.rollback else 'Release'} plan for {self.stack_name}",
            "",
            f"- Release: `{self.release_sha}`",
            f"- Live stack: {live}",
            "- Executes the change set" if self.execute else "- Creates a change set for review",
            "",
            "| Parameter | Value | Source | Change |",
            "| --- | --- | --- | --- |",
        ]
        for name, value in self.parameters.items():
            before = self.live_parameters.get(name)
            if before == value.value:
                change = ""
            else:
                change = "new" if before is None else f"was {_code(before)}"
            lines.append(f"| {name} | {_code(value.value)} | {value.source} | {change} |")
        if self.warnings:
            lines += ["", *(f"> Warning: {warning}" for warning in self.warnings)]
        return lines

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> ReleasePlan:
        data = json.loads(text)
        data["parameters"] = {
            name: Value(**value) for name, value in data["parameters"].items()
        }
        return cls(**data)


def _quoted(value: str) -> str:
    """A --parameter-overrides value as SAM CLI reads it back.

    SAM CLI refuses ``Key=`` and cuts an unquoted value at its first space,
    so every value goes in double quotes, which it strips again along with
    the backslash before an inner quote.
    """
    return '"' + value.replace('"', '\\"') + '"'


def _code(text: str) -> str:
    return f"`{text}`" if text else "(empty)"


def resolve(
    model: TemplateModel,
    live: Mapping[str, str],
    explicit: Mapping[str, str],
    unless_empty: Mapping[str, str],
) -> dict[str, Value]:
    """Every parameter's value except the images, which always follow the release SHA."""
    parameters = model.parameter_definitions()
    images = model.image_parameters()
    given = [*explicit, *unless_empty]
    problems = [f"{name} is not a template parameter" for name in given if name not in parameters]
    problems += [
        f"{name} always points at the release SHA, so it cannot be set"
        for name in given
        if name in images
    ]
    values: dict[str, Value] = {}
    for name, parameter in parameters.items():
        if name in images:
            continue
        if name in explicit:
            values[name] = Value(explicit[name], "set")
        elif unless_empty.get(name):
            values[name] = Value(unless_empty[name], "set")
        elif name in live:
            values[name] = Value(live[name], "live")
        elif parameter.default is not None:
            values[name] = Value(parameter.default, "default")
        else:
            problems.append(
                f"{name} has no default and is not on the stack yet: pass --set {name}=..."
            )
    if problems:
        raise ReleaseError(problems)
    return values


def previous_release_sha(stack: LiveStack | None) -> str | None:
    """The release a stack runs now: the full SHA its API image is tagged with."""
    if stack is None:
        return None
    tag = stack.parameters.get("ApiImageUri", "").rpartition(":")[2]
    return tag if FULL_SHA.fullmatch(tag) else None


def plan_release(
    aws: Aws,
    *,
    stack_name: str,
    region: str,
    release_sha: str,
    explicit: Mapping[str, str],
    unless_empty: Mapping[str, str],
    execute: bool,
    execution_role: bool = True,
    template: Path = TEMPLATE_PATH,
) -> ReleasePlan:
    """Plan a deploy of the images built from ``release_sha``.

    ``execute`` needs a live stack: a new stack is only ever created through
    a change set someone has reviewed.
    """
    return _plan(
        aws,
        template,
        stack_name,
        region,
        release_sha,
        explicit,
        unless_empty,
        execute=execute,
        rollback=False,
        execution_role=execution_role,
    )


def plan_rollback(
    aws: Aws,
    *,
    stack_name: str,
    region: str,
    release_sha: str,
    execution_role: bool = True,
    template: Path = TEMPLATE_PATH,
) -> ReleasePlan:
    """Plan a change set that keeps every live value and swaps the images back.

    A parameter the template has gained since the stack was deployed takes
    its default. The rollback images must still be in ECR.
    """
    return _plan(
        aws,
        template,
        stack_name,
        region,
        release_sha,
        {},
        {},
        execute=False,
        rollback=True,
        execution_role=execution_role,
    )


def _plan(
    aws: Aws,
    template: Path,
    stack_name: str,
    region: str,
    release_sha: str,
    explicit: Mapping[str, str],
    unless_empty: Mapping[str, str],
    *,
    execute: bool,
    rollback: bool,
    execution_role: bool,
) -> ReleasePlan:
    if not FULL_SHA.fullmatch(release_sha):
        raise ReleaseError(
            [f"The release SHA must be a full 40-character Git SHA, not {release_sha!r}"]
        )
    model = template_model(template)
    stack = aws.stack(stack_name)
    if stack is None and rollback:
        raise ReleaseError([f"{stack_name} does not exist, so there is nothing to roll back"])
    if stack is None and execute:
        raise ReleaseError(
            [f"{stack_name} does not exist yet. Create it through a reviewed change set (--no-execute)."]
        )
    live = stack.parameters if stack is not None else {}
    values = resolve(model, live, explicit, unless_empty)

    account_id = aws.account_id()
    registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    images, image_repositories = _images(model, registry, release_sha)
    values.update(images)

    problems: list[str] = []
    warnings = [
        f"{name} is on the live stack but not in the template, so this deploy drops it"
        for name in live
        if name not in model.parameters
    ]
    if not rollback and values["FrontendBaseUrl"].source != "set":
        values["FrontendBaseUrl"], link_problems, link_warnings = _frontend_base_url(
            values, stack, stack_name
        )
        problems += link_problems
        warnings += link_warnings
    previous = previous_release_sha(stack)
    if execute and previous is None:
        problems.append(
            "The live ApiImageUri is not tagged with a full release SHA, so a failed "
            "health check could not prepare a rollback"
        )
    if rollback:
        problems += _missing_images(aws, release_sha)

    plain = {name: value.value for name, value in values.items()}
    for name, parameter in model.parameter_definitions().items():
        problems += parameter.problems(plain[name])
    problems += model.rule_failures(plain)
    text = template.read_bytes()
    if len(text) > INLINE_TEMPLATE_LIMIT:
        problems.append(
            f"{template} is {len(text)} bytes. sam deploy sends at most "
            f"{INLINE_TEMPLATE_LIMIT} bytes without an S3 bucket, and the deploy role has none."
        )
    problems += _secret_problems(model, aws, plain)
    if problems:
        raise ReleaseError(problems)

    return ReleasePlan(
        stack_name=stack_name,
        region=region,
        release_sha=release_sha,
        registry=registry,
        role_arn=(
            f"arn:aws:iam::{account_id}:role/{CLOUDFORMATION_ROLE_NAME}"
            if execution_role
            else None
        ),
        execute=execute,
        rollback=rollback,
        template=str(template),
        template_sha256=hashlib.sha256(text).hexdigest(),
        stack_status=stack.status if stack is not None else None,
        previous_release_sha=previous,
        parameters={name: values[name] for name in model.parameters},
        live_parameters=dict(live),
        image_repositories=image_repositories,
        warnings=warnings,
    )


def _images(
    model: TemplateModel, registry: str, release_sha: str
) -> tuple[dict[str, Value], dict[str, str]]:
    """The image parameters' values, and the repository of every image function.

    SAM CLI refuses a deploy unless --image-repositories names every image
    function and nothing else.
    """
    problems = []
    images = {}
    for parameter in model.image_parameters():
        if parameter in IMAGE_REPOSITORIES:
            images[parameter] = Value(
                f"{registry}/{IMAGE_REPOSITORIES[parameter]}:{release_sha}", "image"
            )
        else:
            problems.append(f"{parameter} has no ECR repository in IMAGE_REPOSITORIES")
    functions = model.functions()
    repositories = {}
    for function in model.image_functions():
        parameter = functions[function].image_parameter
        if parameter is None:
            problems.append(f"{function} does not take its ImageUri from a parameter")
        elif parameter in IMAGE_REPOSITORIES:
            repositories[function] = f"{registry}/{IMAGE_REPOSITORIES[parameter]}"
    if problems:
        raise ReleaseError(problems)
    return images, repositories


def _frontend_base_url(
    values: Mapping[str, Value], stack: LiveStack | None, stack_name: str
) -> tuple[Value, list[str], list[str]]:
    """Where alert and verification emails link to, with any problems and warnings.

    The template cannot work this out itself. ApiFunction's FRONTEND_BASE_URL
    would refer to FrontendDistribution, whose API origin refers to
    ServerlessHttpApi, whose routes refer back to ApiFunction.
    """
    domain = values["SiteDomainName"].value
    if domain:
        return Value(f"https://{domain}", "derived"), [], []
    current = values["FrontendBaseUrl"]
    if stack is not None:
        url = stack.outputs.get("FrontendUrl", "")
        if url and url != "None":
            return Value(url, "derived"), [], []
        return current, [f"{stack_name} has no FrontendUrl output for emails to link to"], []
    problems = []
    if values["NotificationsEnabled"].value == "true":
        problems.append(
            f"Notifications cannot start with the stack: emails would link to "
            f"{current.value}. Set SiteDomainName, or turn notifications on in a later release."
        )
    warning = (
        f"FrontendBaseUrl stays {current.value} until the stack has a FrontendUrl "
        "output. The next release links emails to the live site."
    )
    return current, problems, [warning]


def _missing_images(aws: Aws, release_sha: str) -> list[str]:
    return [
        f"{repository}:{release_sha} is not in ECR"
        for repository in IMAGE_REPOSITORIES.values()
        if not aws.image_exists(repository, release_sha)
    ]


def _secret_problems(model: TemplateModel, aws: Aws, values: Mapping[str, str]) -> list[str]:
    """Each secret behind a switch that is on must exist as a SecureString."""
    problems = []
    for secret, switch in model.gated_secrets().items():
        if values[switch] != "true":
            continue
        name = substitute(secret, values)
        parameter_type = aws.parameter_type(name)
        if parameter_type is None:
            problems.append(f"{switch} is true, but {name} does not exist")
        elif parameter_type != "SecureString":
            problems.append(f"{name} must be a SecureString, not a {parameter_type}")
    return problems


def apply(plan: ReleasePlan, aws: Aws, run: Run = _stream, *, dry_run: bool = False) -> list[str]:
    """Run the plan's sam deploy and return the command, or only print it with ``dry_run``.

    The template must be the one the plan was made from, and the release
    images must be in ECR. A dry run makes no AWS call.
    """
    template = Path(plan.template)
    if (
        not template.is_file()
        or hashlib.sha256(template.read_bytes()).hexdigest() != plan.template_sha256
    ):
        raise ReleaseError([f"{plan.template} has changed since the plan was made"])
    command = plan.sam_deploy_command()
    if dry_run:
        print(shlex.join(command))
        return command
    missing = _missing_images(aws, plan.release_sha)
    if missing:
        raise ReleaseError(missing)
    exit_code = run(command)
    if exit_code:
        raise ReleaseError([f"sam deploy exited with {exit_code}"])
    return command


def stack_outputs(
    model: TemplateModel, aws: Aws, stack_name: str, keys: Sequence[str]
) -> dict[str, str]:
    """The values of these template outputs on the live stack, from one call."""
    unknown = [key for key in keys if key not in model.outputs]
    if unknown:
        raise ReleaseError([f"{key} is not an output of the template" for key in unknown])
    stack = aws.stack(stack_name)
    if stack is None:
        raise ReleaseError([f"{stack_name} does not exist"])
    missing = [key for key in keys if stack.outputs.get(key, "") in ("", "None")]
    if missing:
        raise ReleaseError([f"{stack_name} has no {key} output" for key in missing])
    return {key: stack.outputs[key] for key in keys}


def _append_to(variable: str, text: str) -> None:
    """Append to a GitHub Actions file such as $GITHUB_OUTPUT. Outside Actions, do nothing."""
    path = os.environ.get(variable)
    if path:
        with open(path, "a", encoding="utf-8") as file:
            file.write(text)


def _pair(text: str) -> tuple[str, str]:
    key, separator, value = text.partition("=")
    if not separator or not key:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, not {text!r}")
    return key, value


def _plan_command(args: argparse.Namespace, aws: Aws) -> None:
    given = [key for key, _value in [*args.explicit, *args.unless_empty]]
    repeated = sorted({key for key in given if given.count(key) > 1})
    if repeated:
        raise ReleaseError([f"{key} is given more than once" for key in repeated])
    if args.rollback:
        if args.execute or given:
            raise ReleaseError(
                [
                    "A rollback keeps every live value and only creates a change set: "
                    "use --no-execute and no --set or --set-unless-empty"
                ]
            )
        plan = plan_rollback(
            aws,
            stack_name=args.stack_name,
            region=args.region,
            release_sha=args.release_sha,
            execution_role=args.execution_role,
        )
    else:
        plan = plan_release(
            aws,
            stack_name=args.stack_name,
            region=args.region,
            release_sha=args.release_sha,
            explicit=dict(args.explicit),
            unless_empty=dict(args.unless_empty),
            execute=args.execute,
            execution_role=args.execution_role,
        )
    Path(args.out).write_text(plan.to_json(), encoding="utf-8")
    summary = "\n".join(plan.summary()) + "\n"
    sys.stdout.write(summary)
    _append_to("GITHUB_STEP_SUMMARY", summary)
    _append_to(
        "GITHUB_OUTPUT",
        f"registry={plan.registry}\n"
        f"release_sha={plan.release_sha}\n"
        f"previous_release_sha={plan.previous_release_sha or ''}\n",
    )
    for warning in plan.warnings:
        print(f"::warning::{warning}", file=sys.stderr)


def _outputs_command(args: argparse.Namespace, aws: Aws) -> None:
    names = {}
    for item in args.keys:
        key, _separator, name = item.partition("=")
        names[key] = name or key
    values = stack_outputs(template_model(), aws, args.stack_name, list(names))
    if args.shell:
        for key, value in values.items():
            print(f"export {names[key]}={shlex.quote(value)}")
        return
    lines = "".join(f"{names[key]}={value}\n" for key, value in values.items())
    if args.github_env:
        _append_to("GITHUB_ENV", lines)
    else:
        sys.stdout.write(lines)


def _previous_release_command(args: argparse.Namespace, aws: Aws) -> None:
    stack = aws.stack(args.stack_name)
    if stack is None:
        raise ReleaseError([f"{args.stack_name} does not exist"])
    sha = previous_release_sha(stack)
    if sha is None:
        raise ReleaseError(["The live ApiImageUri is not tagged with a full release SHA"])
    print(sha)
    _append_to("GITHUB_OUTPUT", f"previous_release_sha={sha}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.release", description=__doc__.splitlines()[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="work out and check every parameter")
    plan.add_argument("--stack-name", required=True)
    plan.add_argument("--region", required=True)
    plan.add_argument("--release-sha", required=True, help="full Git SHA the images are tagged with")
    mode = plan.add_mutually_exclusive_group(required=True)
    mode.add_argument("--execute", action="store_true", help="apply the change set")
    mode.add_argument(
        "--no-execute",
        dest="execute",
        action="store_false",
        help="only create a change set for review",
    )
    plan.add_argument(
        "--rollback",
        action="store_true",
        help="keep every live value and point the images at --release-sha",
    )
    plan.add_argument(
        "--no-execution-role",
        dest="execution_role",
        action="store_false",
        help="deploy with the caller's own permissions, before infra/github-oidc.yaml exists",
    )
    plan.add_argument(
        "--set",
        dest="explicit",
        type=_pair,
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="use this value, even an empty one",
    )
    plan.add_argument(
        "--set-unless-empty",
        dest="unless_empty",
        type=_pair,
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="use this value unless it is empty",
    )
    plan.add_argument("--out", required=True, help="where to write the plan")

    apply_command = commands.add_parser("apply", help="run a plan's sam deploy")
    apply_command.add_argument("plan", help="a file written by plan")
    apply_command.add_argument(
        "--dry-run", action="store_true", help="print the sam deploy command instead"
    )

    outputs = commands.add_parser("outputs", help="read the live stack's outputs")
    outputs.add_argument("--stack-name", required=True)
    outputs.add_argument("--region", required=True)
    target = outputs.add_mutually_exclusive_group()
    target.add_argument("--github-env", action="store_true", help="append NAME=value to $GITHUB_ENV")
    target.add_argument("--shell", action="store_true", help="print export lines to eval")
    outputs.add_argument("keys", nargs="+", metavar="Key[=NAME]")

    previous = commands.add_parser(
        "previous-release", help="print the SHA the live stack runs, for a later rollback"
    )
    previous.add_argument("--stack-name", required=True)
    previous.add_argument("--region", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    aws: Aws | None = None,
    run: Run | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            _plan_command(args, aws or AwsCli(args.region))
        elif args.command == "apply":
            plan = ReleasePlan.from_json(Path(args.plan).read_text(encoding="utf-8"))
            apply(plan, aws or AwsCli(plan.region), run or _stream, dry_run=args.dry_run)
        elif args.command == "outputs":
            _outputs_command(args, aws or AwsCli(args.region))
        else:
            _previous_release_command(args, aws or AwsCli(args.region))
    except ReleaseError as error:
        for problem in error.problems:
            print(f"::error::{problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
