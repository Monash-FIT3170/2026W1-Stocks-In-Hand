"""The release module plans and applies every sam deploy of infra/template.yaml.

Nothing here calls AWS: plans are made against a fake account that records
every call, and sam deploy is replaced by a recorder.
"""

import json
import shlex
import subprocess
from pathlib import Path

import pytest

from tools.release import (
    CLOUDFORMATION_ROLE_NAME,
    IMAGE_REPOSITORIES,
    INLINE_TEMPLATE_LIMIT,
    AwsCli,
    LiveStack,
    ReleaseError,
    ReleasePlan,
    Value,
    apply,
    main,
    plan_release,
    plan_rollback,
    resolve,
    stack_outputs,
)
from tools.template_model import REPOSITORY_ROOT, TEMPLATE_PATH, template_model

STACK = "stocks-in-hand-staging"
REGION = "ap-southeast-2"
ACCOUNT = "123456789012"
REGISTRY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
PREFIX = "/stocks-in-hand/staging"


def live_stack(status: str = "UPDATE_COMPLETE", **parameters: str) -> LiveStack:
    """A stack deployed from the template defaults at OLD_SHA."""
    values = {
        name: parameter.default
        for name, parameter in template_model().parameter_definitions().items()
        if parameter.default is not None
    }
    values.update(
        {
            "OperationsEmail": "ops@example.com",
            **{
                parameter: f"{REGISTRY}/{repository}:{OLD_SHA}"
                for parameter, repository in IMAGE_REPOSITORIES.items()
            },
            **parameters,
        }
    )
    outputs = {
        "FrontendUrl": "https://d111.cloudfront.net",
        "ApiEndpoint": "https://d111.cloudfront.net/api",
        "FrontendBucketName": "frontend-bucket",
        "FrontendDistributionId": "E111",
        "AuthProvider": values["AuthProvider"],
    }
    return LiveStack(status, values, outputs)


class FakeAws:
    """An AWS account with at most one stack. It records every call it gets."""

    def __init__(
        self,
        stack: LiveStack | None,
        *,
        images: set[tuple[str, str]] | None = None,
        parameter_types: dict[str, str] | None = None,
    ) -> None:
        self.live = stack
        self.images = (
            {
                (repository, sha)
                for repository in IMAGE_REPOSITORIES.values()
                for sha in (OLD_SHA, NEW_SHA)
            }
            if images is None
            else images
        )
        self.parameter_types = parameter_types or {}
        self.calls: list[tuple[str, ...]] = []

    def account_id(self) -> str:
        self.calls.append(("account_id",))
        return ACCOUNT

    def stack(self, name: str) -> LiveStack | None:
        self.calls.append(("stack", name))
        return self.live

    def image_exists(self, repository: str, tag: str) -> bool:
        self.calls.append(("image_exists", repository, tag))
        return (repository, tag) in self.images

    def parameter_type(self, name: str) -> str | None:
        self.calls.append(("parameter_type", name))
        return self.parameter_types.get(name)


class SamRecorder:
    """Stands in for running sam deploy."""

    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str]) -> int:
        self.commands.append(command)
        return self.exit_code


@pytest.fixture(autouse=True)
def github_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Point the GitHub Actions files at temporary ones, even when CI sets them."""
    files = {}
    for variable in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY", "GITHUB_ENV"):
        files[variable] = tmp_path / variable.lower()
        monkeypatch.setenv(variable, str(files[variable]))
    return files


def plan(aws: FakeAws, *, execute: bool = True, template: Path = TEMPLATE_PATH, **values: str):
    return plan_release(
        aws,
        stack_name=STACK,
        region=REGION,
        release_sha=NEW_SHA,
        explicit=values,
        unless_empty={},
        execute=execute,
        template=template,
    )


def problems(error: pytest.ExceptionInfo[ReleaseError]) -> list[str]:
    return error.value.problems


def overrides(command: list[str]) -> dict[str, str]:
    """The --parameter-overrides of a sam deploy command, unquoted."""
    pairs = [
        item.split("=", 1) for item in command[command.index("--parameter-overrides") + 1 :]
    ]
    assert all(value.startswith('"') and value.endswith('"') for _key, value in pairs)
    return {key: value[1:-1].replace('\\"', '"') for key, value in pairs}


# ---------------------------------------------------------------------------
# One complete sam deploy command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("execute", [True, False], ids=["execute", "change-set-only"])
def test_release_dry_run_prints_one_complete_sam_deploy_command(
    execute: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model = template_model()
    aws = FakeAws(live_stack())
    plan_file = tmp_path / "release-plan.json"
    sam = SamRecorder()

    assert (
        main(
            [
                "plan",
                "--execute" if execute else "--no-execute",
                "--stack-name",
                STACK,
                "--region",
                REGION,
                "--release-sha",
                NEW_SHA,
                "--set",
                "Environment=staging",
                "--set",
                f"ParameterPathPrefix={PREFIX}",
                "--set",
                "OperationsEmail=ops@example.com",
                "--set",
                "SiteDomainName=",
                "--set-unless-empty",
                "AuthProvider=cognito",
                "--set-unless-empty",
                "ScheduleEnabled=",
                "--out",
                str(plan_file),
            ],
            aws=aws,
            run=sam,
        )
        == 0
    )
    calls_after_plan = list(aws.calls)
    capsys.readouterr()

    assert main(["apply", str(plan_file), "--dry-run"], aws=aws, run=sam) == 0
    command = shlex.split(capsys.readouterr().out)

    assert command[:2] == ["sam", "deploy"]
    assert command[command.index("--template-file") + 1] == str(TEMPLATE_PATH)
    repositories = [
        value for flag, value in zip(command, command[1:]) if flag == "--image-repositories"
    ]
    assert sorted(item.split("=", 1)[0] for item in repositories) == model.image_functions()
    for function, repository in (item.split("=", 1) for item in repositories):
        image_parameter = model.function(function).image_parameter
        assert repository == f"{REGISTRY}/{IMAGE_REPOSITORIES[image_parameter]}"
    values = overrides(command)
    assert list(values) == list(model.parameters)
    for parameter, repository in IMAGE_REPOSITORIES.items():
        assert values[parameter] == f"{REGISTRY}/{repository}:{NEW_SHA}"
    assert values["AuthProvider"] == "cognito"
    assert values["SiteDomainName"] == ""
    assert ("--no-execute-changeset" in command) is not execute
    assert command[command.index("--role-arn") + 1] == (
        f"arn:aws:iam::{ACCOUNT}:role/{CLOUDFORMATION_ROLE_NAME}"
    )
    # The dry run neither called AWS nor ran sam.
    assert aws.calls == calls_after_plan
    assert sam.commands == []


def test_the_first_manual_deploy_can_run_without_the_execution_role() -> None:
    planned = plan_release(
        FakeAws(None),
        stack_name=STACK,
        region=REGION,
        release_sha=NEW_SHA,
        explicit={"OperationsEmail": "ops@example.com"},
        unless_empty={},
        execute=False,
        execution_role=False,
    )

    assert "--role-arn" not in planned.sam_deploy_command()


def test_a_value_with_a_space_or_quote_reaches_sam_whole() -> None:
    planned = plan(FakeAws(live_stack()), ScheduledPublicDiscussionSources='a "b" c')

    assert overrides(planned.sam_deploy_command())["ScheduledPublicDiscussionSources"] == 'a "b" c'


def test_a_plan_survives_its_json_file() -> None:
    planned = plan(FakeAws(live_stack()))

    assert ReleasePlan.from_json(planned.to_json()) == planned


# ---------------------------------------------------------------------------
# Where each value comes from
# ---------------------------------------------------------------------------


def test_a_value_comes_from_set_then_set_unless_empty_then_live_then_default() -> None:
    model = template_model()
    live = {"AuthProvider": "dual", "ScheduleEnabled": "true", "BedrockEnabled": "true"}

    values = resolve(
        model,
        live,
        {"AuthProvider": "cognito", "OperationsEmail": "ops@example.com"},
        {"AuthProvider": "legacy", "ScheduleEnabled": "false", "BedrockEnabled": ""},
    )

    assert values["AuthProvider"] == Value("cognito", "set")
    assert values["ScheduleEnabled"] == Value("false", "set")
    assert values["BedrockEnabled"] == Value("true", "live")
    assert values["MarketauxPerTickerLimit"] == Value("10", "default")
    assert set(values) == set(model.parameters) - set(IMAGE_REPOSITORIES)


def test_an_explicitly_empty_value_replaces_the_live_one() -> None:
    values = resolve(
        template_model(),
        {"OperationsEmail": "ops@example.com", "SiteDomainName": "app.example.com"},
        {"SiteDomainName": ""},
        {},
    )

    assert values["SiteDomainName"] == Value("", "set")


def test_unknown_image_and_missing_values_are_refused_together() -> None:
    with pytest.raises(ReleaseError) as error:
        resolve(
            template_model(),
            {},
            {"ApiImageUri": "elsewhere:latest", "Unknown": "1"},
            {"AlsoUnknown": "2"},
        )

    assert problems(error) == [
        "Unknown is not a template parameter",
        "AlsoUnknown is not a template parameter",
        "ApiImageUri always points at the release SHA, so it cannot be set",
        "OperationsEmail has no default and is not on the stack yet: pass --set OperationsEmail=...",
    ]


def test_a_key_given_twice_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    aws = FakeAws(live_stack())

    exit_code = main(
        [
            "plan",
            "--no-execute",
            "--stack-name",
            STACK,
            "--region",
            REGION,
            "--release-sha",
            NEW_SHA,
            "--set",
            "AuthProvider=cognito",
            "--set-unless-empty",
            "AuthProvider=dual",
            "--out",
            str(tmp_path / "plan.json"),
        ],
        aws=aws,
    )

    assert exit_code == 1
    assert capsys.readouterr().err.splitlines() == ["::error::AuthProvider is given more than once"]
    assert aws.calls == []


def test_every_value_is_checked_against_its_constraints_and_the_rules() -> None:
    with pytest.raises(ReleaseError) as error:
        plan(
            FakeAws(live_stack(), parameter_types={f"{PREFIX}/brevo-api-key": "SecureString"}),
            AuthProvider="okta",
            MarketauxPerTickerLimit="26",
            OperationsEmail="not-an-email",
            NotificationsEnabled="true",
            AlertSenderEmail="",
            SiteDomainName="app.example.com",
        )

    assert problems(error) == [
        "OperationsEmail 'not-an-email' does not match ^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$",
        "AuthProvider must be one of legacy, dual, cognito, not 'okta'",
        "MarketauxPerTickerLimit must be at most 25, not 26",
        "AlertSenderEmail is required when notifications are enabled.",
        "SiteCertificateArn is required when SiteDomainName is set.",
        "SiteHostedZoneId is required when SiteDomainName is set.",
    ]


def test_the_template_fits_in_a_sam_deploy_without_an_s3_bucket() -> None:
    assert TEMPLATE_PATH.stat().st_size <= INLINE_TEMPLATE_LIMIT


def test_a_template_too_large_to_send_inline_is_refused(tmp_path: Path) -> None:
    template = tmp_path / "template.yaml"
    text = TEMPLATE_PATH.read_bytes()
    # A trailing YAML comment takes the file one byte over the limit.
    template.write_bytes(text + b"#" * (INLINE_TEMPLATE_LIMIT + 1 - len(text)))

    with pytest.raises(ReleaseError) as error:
        plan(FakeAws(live_stack()), template=template)

    [problem] = problems(error)
    assert problem.startswith(f"{template} is {INLINE_TEMPLATE_LIMIT + 1} bytes")


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (
            ("ImageUri: !Ref AnalysisImageUri", "ImageUri: example.invalid/analysis:latest"),
            "AnalysisFunction does not take its ImageUri from a parameter",
        ),
        (
            ("ApiImageUri", "WorkerImageUri"),
            "WorkerImageUri has no ECR repository in IMAGE_REPOSITORIES",
        ),
    ],
    ids=["fixed-image", "unknown-repository"],
)
def test_every_image_function_must_map_to_a_release_repository(
    change: tuple[str, str], problem: str, tmp_path: Path
) -> None:
    template = tmp_path / "template.yaml"
    template.write_bytes(TEMPLATE_PATH.read_bytes().replace(*(part.encode() for part in change)))

    with pytest.raises(ReleaseError) as error:
        plan(FakeAws(live_stack()), template=template)

    assert problems(error) == [problem]


# ---------------------------------------------------------------------------
# FrontendBaseUrl
# ---------------------------------------------------------------------------

CUSTOM_DOMAIN = {
    "SiteDomainName": "app.example.com",
    "SiteCertificateArn": f"arn:aws:acm:us-east-1:{ACCOUNT}:certificate/abc",
    "SiteHostedZoneId": "Z123",
}


def test_emails_link_to_the_custom_domain_when_there_is_one() -> None:
    planned = plan(FakeAws(live_stack()), **CUSTOM_DOMAIN)

    assert planned.parameters["FrontendBaseUrl"] == Value("https://app.example.com", "derived")


def test_emails_link_to_the_live_frontend_url_without_a_custom_domain() -> None:
    planned = plan(FakeAws(live_stack()), SiteDomainName="")

    assert planned.parameters["FrontendBaseUrl"] == Value("https://d111.cloudfront.net", "derived")


def test_a_live_stack_without_a_frontend_url_output_is_refused() -> None:
    stack = live_stack()
    stack.outputs.pop("FrontendUrl")

    with pytest.raises(ReleaseError) as error:
        plan(FakeAws(stack))

    assert problems(error) == [f"{STACK} has no FrontendUrl output for emails to link to"]


def test_a_new_stack_links_emails_to_the_placeholder_with_a_warning() -> None:
    planned = plan(FakeAws(None), execute=False, OperationsEmail="ops@example.com")

    assert planned.parameters["FrontendBaseUrl"] == Value("https://example.invalid", "default")
    assert planned.warnings == [
        "FrontendBaseUrl stays https://example.invalid until the stack has a FrontendUrl "
        "output. The next release links emails to the live site."
    ]


def test_a_new_stack_cannot_send_emails_to_the_placeholder() -> None:
    aws = FakeAws(None, parameter_types={f"{PREFIX}/brevo-api-key": "SecureString"})

    with pytest.raises(ReleaseError) as error:
        plan(
            aws,
            execute=False,
            OperationsEmail="ops@example.com",
            NotificationsEnabled="true",
            AlertSenderEmail="alerts@example.com",
        )

    assert problems(error) == [
        "Notifications cannot start with the stack: emails would link to "
        "https://example.invalid. Set SiteDomainName, or turn notifications on "
        "in a later release."
    ]


def test_an_explicit_frontend_base_url_is_used_as_given() -> None:
    planned = plan(
        FakeAws(None),
        execute=False,
        OperationsEmail="ops@example.com",
        FrontendBaseUrl="https://example.org",
    )

    assert planned.parameters["FrontendBaseUrl"] == Value("https://example.org", "set")
    assert planned.warnings == []


# ---------------------------------------------------------------------------
# New stacks and the previous release
# ---------------------------------------------------------------------------


def test_a_new_stack_takes_its_values_from_the_flags_and_the_defaults() -> None:
    planned = plan(FakeAws(None), execute=False, OperationsEmail="ops@example.com")

    assert {value.source for value in planned.parameters.values()} == {"set", "default", "image"}
    assert planned.previous_release_sha is None
    assert planned.stack_status is None
    assert "--no-execute-changeset" in planned.sam_deploy_command()


def test_a_new_stack_needs_an_operations_email() -> None:
    with pytest.raises(ReleaseError) as error:
        plan(FakeAws(None), execute=False)

    assert problems(error) == [
        "OperationsEmail has no default and is not on the stack yet: pass --set OperationsEmail=..."
    ]


def test_execute_refuses_to_create_a_stack() -> None:
    with pytest.raises(ReleaseError) as error:
        plan(FakeAws(None), OperationsEmail="ops@example.com")

    assert problems(error) == [
        f"{STACK} does not exist yet. Create it through a reviewed change set (--no-execute)."
    ]


def test_the_previous_release_is_the_sha_the_live_api_image_is_tagged_with() -> None:
    assert plan(FakeAws(live_stack())).previous_release_sha == OLD_SHA


@pytest.mark.parametrize(
    "image",
    ["", f"{REGISTRY}/stocks-in-hand-api:latest", f"{REGISTRY}/stocks-in-hand-api:{OLD_SHA[:12]}"],
    ids=["empty", "latest", "short"],
)
def test_execute_refuses_a_live_stack_without_a_full_release_sha(image: str) -> None:
    aws = FakeAws(live_stack(ApiImageUri=image))

    assert plan(aws, execute=False).previous_release_sha is None
    with pytest.raises(ReleaseError) as error:
        plan(aws)

    assert problems(error) == [
        "The live ApiImageUri is not tagged with a full release SHA, so a failed "
        "health check could not prepare a rollback"
    ]


@pytest.mark.parametrize(
    ("stack", "problem"),
    [
        (None, f"{STACK} does not exist"),
        (
            live_stack(ApiImageUri=f"{REGISTRY}/stocks-in-hand-api:latest"),
            "The live ApiImageUri is not tagged with a full release SHA",
        ),
    ],
    ids=["no-stack", "no-sha"],
)
def test_the_previous_release_command_refuses_a_stack_without_one(
    stack: LiveStack | None, problem: str, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["previous-release", "--stack-name", STACK, "--region", REGION]

    assert main(arguments, aws=FakeAws(stack)) == 1
    assert capsys.readouterr().err.splitlines() == [f"::error::{problem}"]


def test_the_previous_release_command_writes_the_live_sha(
    github_files: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    aws = FakeAws(live_stack())

    assert main(["previous-release", "--stack-name", STACK, "--region", REGION], aws=aws) == 0
    assert capsys.readouterr().out == f"{OLD_SHA}\n"
    assert github_files["GITHUB_OUTPUT"].read_text(encoding="utf-8") == (
        f"previous_release_sha={OLD_SHA}\n"
    )
    assert aws.calls == [("stack", STACK)]


def test_a_parameter_no_longer_in_the_template_is_dropped_with_a_warning() -> None:
    planned = plan(FakeAws(live_stack(RetiredSwitch="true")))

    assert "RetiredSwitch" not in planned.parameters
    assert planned.warnings == [
        "RetiredSwitch is on the live stack but not in the template, so this deploy drops it"
    ]


# ---------------------------------------------------------------------------
# Secrets behind a switch
# ---------------------------------------------------------------------------


def test_a_secret_is_checked_only_while_its_switch_is_on() -> None:
    aws = FakeAws(
        live_stack(),
        parameter_types={f"{PREFIX}/marketaux-api-token": "SecureString"},
    )

    plan(aws, MarketauxEnabled="false")
    assert not [call for call in aws.calls if call[0] == "parameter_type"]

    plan(aws, MarketauxEnabled="true")
    assert ("parameter_type", f"{PREFIX}/marketaux-api-token") in aws.calls


@pytest.mark.parametrize(
    ("parameter_type", "problem"),
    [
        (None, f"MarketauxEnabled is true, but {PREFIX}/marketaux-api-token does not exist"),
        ("String", f"{PREFIX}/marketaux-api-token must be a SecureString, not a String"),
    ],
)
def test_a_secret_behind_a_switch_that_is_on_must_be_a_secure_string(
    parameter_type: str | None, problem: str
) -> None:
    types = {} if parameter_type is None else {f"{PREFIX}/marketaux-api-token": parameter_type}

    with pytest.raises(ReleaseError) as error:
        plan(FakeAws(live_stack(), parameter_types=types), MarketauxEnabled="true")

    assert problems(error) == [problem]


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def rollback(aws: FakeAws, release_sha: str = OLD_SHA):
    return plan_rollback(aws, stack_name=STACK, region=REGION, release_sha=release_sha)


def test_rollback_keeps_every_live_value_and_swaps_only_the_images() -> None:
    stack = live_stack(
        AuthProvider="cognito",
        ScheduleEnabled="true",
        BedrockEnabled="true",
        AlertSenderEmail="alerts@example.com",
        FrontendBaseUrl="https://app.example.com",
        ApiImageUri=f"{REGISTRY}/stocks-in-hand-api:{NEW_SHA}",
        ScraperImageUri=f"{REGISTRY}/stocks-in-hand-scraper:{NEW_SHA}",
        AnalysisImageUri=f"{REGISTRY}/stocks-in-hand-analysis:{NEW_SHA}",
        **CUSTOM_DOMAIN,
    )

    planned = rollback(FakeAws(stack))

    changed = {
        name: value.value
        for name, value in planned.parameters.items()
        if value.value != stack.parameters[name]
    }
    assert changed == {
        parameter: f"{REGISTRY}/{repository}:{OLD_SHA}"
        for parameter, repository in IMAGE_REPOSITORIES.items()
    }
    assert {value.source for value in planned.parameters.values()} == {"live", "image"}
    assert (planned.execute, planned.rollback, planned.previous_release_sha) == (
        False,
        True,
        NEW_SHA,
    )
    assert "--no-execute-changeset" in planned.sam_deploy_command()


def test_rollback_gives_a_parameter_new_to_the_template_its_default() -> None:
    stack = live_stack()
    stack.parameters.pop("AlertDailyBudget")

    planned = rollback(FakeAws(stack))

    assert planned.parameters["AlertDailyBudget"] == Value("180", "default")


def test_rollback_refuses_a_missing_stack() -> None:
    with pytest.raises(ReleaseError) as error:
        rollback(FakeAws(None))

    assert problems(error) == [f"{STACK} does not exist, so there is nothing to roll back"]


def test_rollback_refuses_a_short_sha_before_calling_aws() -> None:
    aws = FakeAws(live_stack())

    with pytest.raises(ReleaseError) as error:
        rollback(aws, OLD_SHA[:7])

    assert problems(error) == [
        f"The release SHA must be a full 40-character Git SHA, not '{OLD_SHA[:7]}'"
    ]
    assert aws.calls == []


def test_rollback_refuses_a_release_whose_images_are_gone() -> None:
    aws = FakeAws(live_stack(), images={("stocks-in-hand-api", OLD_SHA)})

    with pytest.raises(ReleaseError) as error:
        rollback(aws)

    assert problems(error) == [
        f"stocks-in-hand-scraper:{OLD_SHA} is not in ECR",
        f"stocks-in-hand-analysis:{OLD_SHA} is not in ECR",
    ]


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def test_apply_runs_sam_deploy_once_the_release_images_exist() -> None:
    aws = FakeAws(live_stack())
    planned = plan(aws)
    sam = SamRecorder()

    command = apply(planned, aws, sam)

    assert sam.commands == [command] == [planned.sam_deploy_command()]
    assert [call for call in aws.calls if call[0] == "image_exists"] == [
        ("image_exists", repository, NEW_SHA) for repository in IMAGE_REPOSITORIES.values()
    ]


def test_apply_refuses_a_release_image_that_was_never_pushed() -> None:
    aws = FakeAws(live_stack())
    planned = plan(aws)
    aws.images.discard(("stocks-in-hand-analysis", NEW_SHA))
    sam = SamRecorder()

    with pytest.raises(ReleaseError) as error:
        apply(planned, aws, sam)

    assert problems(error) == [f"stocks-in-hand-analysis:{NEW_SHA} is not in ECR"]
    assert sam.commands == []


def test_apply_refuses_a_template_changed_since_the_plan(tmp_path: Path) -> None:
    template = tmp_path / "template.yaml"
    template.write_bytes(TEMPLATE_PATH.read_bytes())
    aws = FakeAws(live_stack())
    planned = plan(aws, template=template)
    template.write_bytes(TEMPLATE_PATH.read_bytes() + b"\n")
    sam = SamRecorder()

    with pytest.raises(ReleaseError) as error:
        apply(planned, aws, sam, dry_run=True)

    assert problems(error) == [f"{planned.template} has changed since the plan was made"]
    assert sam.commands == []


def test_apply_reports_a_failed_sam_deploy(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    aws = FakeAws(live_stack())
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(plan(aws).to_json(), encoding="utf-8")

    assert main(["apply", str(plan_file)], aws=aws, run=SamRecorder(exit_code=1)) == 1
    assert capsys.readouterr().err.splitlines() == ["::error::sam deploy exited with 1"]


# ---------------------------------------------------------------------------
# The plan command's GitHub Actions output
# ---------------------------------------------------------------------------


def test_plan_writes_its_outputs_and_a_parameter_table(
    tmp_path: Path, github_files: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    aws = FakeAws(live_stack())

    assert (
        main(
            [
                "plan",
                "--execute",
                "--stack-name",
                STACK,
                "--region",
                REGION,
                "--release-sha",
                NEW_SHA,
                "--set-unless-empty",
                "AuthProvider=cognito",
                "--out",
                str(tmp_path / "plan.json"),
            ],
            aws=aws,
        )
        == 0
    )

    assert github_files["GITHUB_OUTPUT"].read_text(encoding="utf-8").splitlines() == [
        f"registry={REGISTRY}",
        f"release_sha={NEW_SHA}",
        f"previous_release_sha={OLD_SHA}",
    ]
    summary = github_files["GITHUB_STEP_SUMMARY"].read_text(encoding="utf-8")
    assert summary == capsys.readouterr().out
    assert "| AuthProvider | `cognito` | set | was `legacy` |" in summary
    assert "| ScheduleEnabled | `false` | live |  |" in summary
    assert (
        f"| ApiImageUri | `{REGISTRY}/stocks-in-hand-api:{NEW_SHA}` | image | "
        f"was `{REGISTRY}/stocks-in-hand-api:{OLD_SHA}` |"
    ) in summary


def test_plan_reports_every_problem_as_a_github_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "plan",
            "--no-execute",
            "--stack-name",
            STACK,
            "--region",
            REGION,
            "--release-sha",
            NEW_SHA,
            "--set",
            "AuthProvider=okta",
            "--set",
            "MarketauxPerTickerLimit=0",
            "--out",
            str(tmp_path / "plan.json"),
        ],
        aws=FakeAws(live_stack()),
    )

    assert exit_code == 1
    assert capsys.readouterr().err.splitlines() == [
        "::error::AuthProvider must be one of legacy, dual, cognito, not 'okta'",
        "::error::MarketauxPerTickerLimit must be at least 1, not 0",
    ]
    assert not (tmp_path / "plan.json").exists()


@pytest.mark.parametrize("extra", [["--execute"], ["--no-execute", "--set", "AuthProvider=legacy"]])
def test_a_rollback_takes_no_values_and_never_executes(
    extra: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "plan",
            "--rollback",
            *extra,
            "--stack-name",
            STACK,
            "--region",
            REGION,
            "--release-sha",
            OLD_SHA,
            "--out",
            str(tmp_path / "plan.json"),
        ],
        aws=FakeAws(live_stack()),
    )

    assert exit_code == 1
    assert capsys.readouterr().err.splitlines() == [
        "::error::A rollback keeps every live value and only creates a change set: "
        "use --no-execute and no --set or --set-unless-empty"
    ]


# ---------------------------------------------------------------------------
# Stack outputs
# ---------------------------------------------------------------------------


def test_outputs_are_read_with_one_call() -> None:
    aws = FakeAws(live_stack())

    assert stack_outputs(template_model(), aws, STACK, ["ApiEndpoint", "FrontendBucketName"]) == {
        "ApiEndpoint": "https://d111.cloudfront.net/api",
        "FrontendBucketName": "frontend-bucket",
    }
    assert aws.calls == [("stack", STACK)]


def test_outputs_refuse_unknown_keys_and_missing_values() -> None:
    stack = live_stack()
    stack.outputs["FrontendDistributionId"] = "None"

    with pytest.raises(ReleaseError) as unknown:
        stack_outputs(template_model(), FakeAws(stack), STACK, ["ApiEndpoint", "Nope"])
    with pytest.raises(ReleaseError) as missing:
        stack_outputs(
            template_model(), FakeAws(stack), STACK, ["FrontendDistributionId", "SiteUrl"]
        )
    with pytest.raises(ReleaseError) as no_stack:
        stack_outputs(template_model(), FakeAws(None), STACK, ["ApiEndpoint"])

    assert problems(unknown) == ["Nope is not an output of the template"]
    assert problems(missing) == [
        f"{STACK} has no FrontendDistributionId output",
        f"{STACK} has no SiteUrl output",
    ]
    assert problems(no_stack) == [f"{STACK} does not exist"]


def test_outputs_go_to_the_github_env_file_or_the_shell(
    github_files: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    stack = live_stack()
    stack.outputs["FrontendBucketName"] = "bucket with 'quote'"
    keys = ["ApiEndpoint=API_ENDPOINT", "FrontendBucketName=FRONTEND_BUCKET", "FrontendUrl"]
    arguments = ["outputs", "--stack-name", STACK, "--region", REGION]

    assert main([*arguments, "--github-env", *keys], aws=FakeAws(stack)) == 0
    assert main([*arguments, "--shell", *keys], aws=FakeAws(stack)) == 0

    assert github_files["GITHUB_ENV"].read_text(encoding="utf-8").splitlines() == [
        "API_ENDPOINT=https://d111.cloudfront.net/api",
        "FRONTEND_BUCKET=bucket with 'quote'",
        "FrontendUrl=https://d111.cloudfront.net",
    ]
    assert capsys.readouterr().out.splitlines() == [
        "export API_ENDPOINT=https://d111.cloudfront.net/api",
        "export FRONTEND_BUCKET='bucket with '\"'\"'quote'\"'\"''",
        "export FrontendUrl=https://d111.cloudfront.net",
    ]


# ---------------------------------------------------------------------------
# The ECR repositories and the AWS CLI adapter
# ---------------------------------------------------------------------------


def test_image_repositories_match_bootstrap_and_the_template() -> None:
    bootstrap = template_model(REPOSITORY_ROOT / "infra" / "bootstrap.yaml")

    assert sorted(IMAGE_REPOSITORIES.values()) == sorted(
        repository["RepositoryName"]
        for repository in (
            bootstrap.properties(logical_id)
            for logical_id in bootstrap.of_type("AWS::ECR::Repository")
        )
    )
    assert set(IMAGE_REPOSITORIES) == set(template_model().image_parameters())


class AwsCliRun:
    """A fake AWS CLI: answers each command from a table of canned replies."""

    def __init__(self, replies: dict[str, tuple[int, object]]) -> None:
        self.replies = replies
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(argv)
        returncode, reply = self.replies[argv[2]]
        if returncode:
            return subprocess.CompletedProcess(argv, returncode, "", str(reply))
        return subprocess.CompletedProcess(argv, 0, json.dumps(reply), "")


def test_aws_cli_reads_the_stack_images_and_parameter_metadata() -> None:
    run = AwsCliRun(
        {
            "get-caller-identity": (0, {"Account": ACCOUNT}),
            "describe-stacks": (
                0,
                {
                    "Stacks": [
                        {
                            "StackStatus": "UPDATE_COMPLETE",
                            "Parameters": [
                                {"ParameterKey": "AuthProvider", "ParameterValue": "dual"}
                            ],
                            "Outputs": [
                                {"OutputKey": "FrontendUrl", "OutputValue": "https://d.net"}
                            ],
                        }
                    ]
                },
            ),
            "describe-images": (0, {"imageDetails": [{}]}),
            "get-parameter": (0, "SecureString"),
        }
    )
    aws = AwsCli(REGION, run)

    assert aws.account_id() == ACCOUNT
    assert aws.stack(STACK) == LiveStack(
        "UPDATE_COMPLETE", {"AuthProvider": "dual"}, {"FrontendUrl": "https://d.net"}
    )
    assert aws.image_exists("stocks-in-hand-api", NEW_SHA)
    assert aws.parameter_type(f"{PREFIX}/brevo-api-key") == "SecureString"
    assert run.commands == [
        ["aws", "sts", "get-caller-identity", "--region", REGION, "--output", "json"],
        [
            "aws",
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            STACK,
            "--region",
            REGION,
            "--output",
            "json",
        ],
        [
            "aws",
            "ecr",
            "describe-images",
            "--repository-name",
            "stocks-in-hand-api",
            "--image-ids",
            f"imageTag={NEW_SHA}",
            "--region",
            REGION,
            "--output",
            "json",
        ],
        [
            "aws",
            "ssm",
            "get-parameter",
            "--name",
            f"{PREFIX}/brevo-api-key",
            "--query",
            "Parameter.Type",
            "--region",
            REGION,
            "--output",
            "json",
        ],
    ]


def test_aws_cli_reads_missing_things_as_absent() -> None:
    aws = AwsCli(
        REGION,
        AwsCliRun(
            {
                # The text SAM CLI also looks for to tell a missing stack apart.
                "describe-stacks": (
                    254,
                    f"An error occurred (ValidationError) when calling the DescribeStacks "
                    f"operation: Stack with id {STACK} does not exist",
                ),
                "describe-images": (
                    254,
                    "An error occurred (ImageNotFoundException) when calling the "
                    "DescribeImages operation: The image requested does not exist",
                ),
                "get-parameter": (
                    254,
                    "An error occurred (ParameterNotFound) when calling the GetParameter operation:",
                ),
            }
        ),
    )

    assert aws.stack(STACK) is None
    assert not aws.image_exists("stocks-in-hand-api", NEW_SHA)
    assert aws.parameter_type(f"{PREFIX}/brevo-api-key") is None


def test_aws_cli_treats_a_stack_still_in_review_as_new() -> None:
    aws = AwsCli(
        REGION,
        AwsCliRun({"describe-stacks": (0, {"Stacks": [{"StackStatus": "REVIEW_IN_PROGRESS"}]})}),
    )

    assert aws.stack(STACK) is None


def test_aws_cli_reports_any_other_failure() -> None:
    aws = AwsCli(
        REGION,
        AwsCliRun(
            {
                "get-parameter": (
                    254,
                    "An error occurred (AccessDeniedException) when calling the GetParameter operation",
                )
            }
        ),
    )

    with pytest.raises(ReleaseError) as error:
        aws.parameter_type(f"{PREFIX}/brevo-api-key")

    assert problems(error) == [
        "aws ssm get-parameter failed: An error occurred (AccessDeniedException) when "
        "calling the GetParameter operation"
    ]
