"""The deploy roles in infra/github-oidc.yaml grant what the staging workflows need.

Each test checks one need against the roles' policies, read through the
template model. The stack, image repositories, secrets, queues and buckets
come from where they are written down: the workflows, the release module and
infra/template.yaml. Nothing here calls AWS. IAM Access Analyzer needs
credentials, and cfn-lint, which CI runs on this template, does not check
what an ARN pattern matches.
"""

import yaml

from tools.release import CLOUDFORMATION_ROLE_NAME, IMAGE_REPOSITORIES
from tools.template_model import (
    REPOSITORY_ROOT,
    TemplateModel,
    branches,
    possible_strings,
    substitute,
    template_model,
)

WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"
GITHUB_ROLE = "GitHubDeploymentRole"
EXECUTION_ROLE = "CloudFormationExecutionRole"
# What the deploy workflows set, and an example account.
STACK = "stocks-in-hand-staging"
REGION = "ap-southeast-2"
PARAMETER_PATH_PREFIX = "/stocks-in-hand/staging"
ACCOUNT = "123456789012"


def _oidc() -> TemplateModel:
    return template_model(REPOSITORY_ROOT / "infra" / "github-oidc.yaml")


def _deploy_jobs() -> list[tuple[str, dict]]:
    """Every workflow job that signs in as the GitHub deploy role, with its workflow file."""
    return [
        (path.name, job)
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].values()
        if any(
            (step.get("with") or {}).get("role-to-assume") == "${{ vars.AWS_DEPLOY_ROLE_ARN }}"
            for step in job.get("steps") or []
        )
    ]


def _role_arn(name: str) -> str:
    return f"arn:aws:iam::{ACCOUNT}:role/{name}"


def _values(**parameters: str) -> dict[str, str]:
    """What CloudFormation fills the OIDC stack's references with: its defaults unless given."""
    oidc = _oidc()
    defaults = {
        name: parameter.default
        for name, parameter in oidc.parameter_definitions().items()
        if parameter.default is not None
    }
    return {
        **defaults,
        **parameters,
        "AWS::Partition": "aws",
        "AWS::Region": REGION,
        "AWS::AccountId": ACCOUNT,
        f"{EXECUTION_ROLE}.Arn": _role_arn(oidc.properties(EXECUTION_ROLE)["RoleName"]),
    }


def _can(role: str, action: str, arn: str, values: dict[str, str]) -> bool:
    return any(
        statement.covers(action, arn, values) for statement in _oidc().role_statements(role)
    )


def test_the_oidc_stack_defines_only_the_staging_deploy_roles() -> None:
    """docs/adr/0001-remove-the-deployment-test-deploy-roles.md says why there are no others.

    A policy resource attached to a role would also grant more than
    role_statements reads, so the stack holds nothing else.
    """
    oidc = _oidc()

    assert set(oidc.resources) == {"GitHubOidcProvider", GITHUB_ROLE, EXECUTION_ROLE}
    assert set(oidc.outputs) == {"GitHubDeploymentRoleArn", "CloudFormationExecutionRoleArn"}


def test_only_staging_jobs_can_sign_in_as_the_github_role() -> None:
    """GitHub names a job's environment in its OIDC token, and the role trusts one environment."""
    oidc = _oidc()
    [trust] = oidc.properties(GITHUB_ROLE)["AssumeRolePolicyDocument"]["Statement"]
    environment = oidc.parameter_definitions()["GitHubEnvironment"].default
    provider = oidc.properties("GitHubOidcProvider")
    jobs = _deploy_jobs()

    assert provider["Url"] == "https://token.actions.githubusercontent.com"
    assert list(branches(trust["Principal"]["Federated"])) == [
        {"Ref": "GitHubOidcProvider"},
        {"Ref": "ExistingOidcProviderArn"},
    ]
    assert trust["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert trust["Condition"] == {
        "StringEquals": {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
            "token.actions.githubusercontent.com:sub": {
                "Fn::Sub": "repo:${GitHubRepository}:environment:${GitHubEnvironment}"
            },
        }
    }
    assert [name for name, _job in jobs] == [
        "deploy-staging.yml",
        "execute-staging-change-set.yml",
        "prepare-staging-backend-rollback.yml",
        "publish-staging-frontend.yml",
        "rollback-staging-frontend.yml",
        "verify-staging-queue-wiring.yml",
    ]
    for name, job in jobs:
        assert job["environment"] == environment, name
        assert (job["env"]["STACK_NAME"], job["env"]["AWS_REGION"]) == (STACK, REGION), name
    assert {
        job["env"]["PARAMETER_PATH_PREFIX"]
        for _name, job in jobs
        if "PARAMETER_PATH_PREFIX" in job["env"]
    } == {PARAMETER_PATH_PREFIX}


def test_the_github_role_changes_only_the_staging_stack_through_the_execution_role() -> None:
    """sam deploy creates and executes change sets, and the other workflows read the stack.

    Every change goes through the execution role, so the GitHub role never
    holds the grants the application's resources need.
    """
    values = _values()
    stack = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{STACK}/1a2b3c4d"
    other_stacks = [
        f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/stocks-in-hand-github-oidc/1a2b3c4d",
        f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{STACK}-copy/1a2b3c4d",
    ]
    changes = (
        "cloudformation:CreateChangeSet",
        "cloudformation:CreateStack",
        "cloudformation:UpdateStack",
    )
    creating = [
        statement
        for statement in _oidc().role_statements(GITHUB_ROLE)
        if any(statement.covers(action, stack, values) for action in changes)
    ]

    for action in (
        "cloudformation:CreateChangeSet",
        "cloudformation:DescribeChangeSet",
        "cloudformation:ListChangeSets",
        "cloudformation:ExecuteChangeSet",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:ListStackResources",
    ):
        assert _can(GITHUB_ROLE, action, stack, values), action
    assert _can(GITHUB_ROLE, "cloudformation:GetTemplateSummary", "*", values)
    assert not _can(GITHUB_ROLE, "cloudformation:DeleteStack", stack, values)
    for action in (*changes, "cloudformation:ExecuteChangeSet", "cloudformation:DeleteChangeSet"):
        for other in other_stacks:
            assert not _can(GITHUB_ROLE, action, other, values), (action, other)
    assert creating
    for statement in creating:
        assert statement.iam_condition == {
            "ArnEquals": {"cloudformation:RoleArn": {"Fn::GetAtt": [EXECUTION_ROLE, "Arn"]}}
        }, statement.sid
    assert _can(GITHUB_ROLE, "iam:PassRole", values[f"{EXECUTION_ROLE}.Arn"], values)
    for role in ("stocks-in-hand-github-staging", "stocks-in-hand-staging-ApiFunctionRole-1A2B"):
        assert not _can(GITHUB_ROLE, "iam:PassRole", _role_arn(role), values), role


def test_the_github_role_can_push_every_release_image_but_never_delete_one() -> None:
    """deploy-staging pushes the images, and a rollback needs the older ones still in ECR."""
    values = _values()
    # docker push, then the image checks of deploy-staging and the release plan.
    actions = (
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:DescribeImages",
    )

    assert _can(GITHUB_ROLE, "ecr:GetAuthorizationToken", "*", values)
    for repository in IMAGE_REPOSITORIES.values():
        arn = f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{repository}"
        for action in actions:
            assert _can(GITHUB_ROLE, action, arn, values), (action, repository)
        assert not _can(GITHUB_ROLE, "ecr:BatchDeleteImage", arn, values), repository


def test_the_github_role_reads_the_type_of_only_the_secrets_a_release_checks() -> None:
    """The release plan checks that each secret behind a switch that is on is a SecureString.

    The role may read that metadata and nothing more: no other parameter the
    application reads, such as the database URL, and no secret's value,
    because it has no kms:Decrypt.
    """
    app = template_model()
    prefix = {"ParameterPathPrefix": PARAMETER_PATH_PREFIX}
    names = {
        substitute(name, prefix)
        for function in app.functions().values()
        for variable, value in function.environment.items()
        if variable.endswith("_PARAMETER")
        for name in possible_strings(value)
        if name
    }
    values = _values()
    readable = {
        name
        for name in names | {f"{PARAMETER_PATH_PREFIX}/a-new-secret"}
        if _can(
            GITHUB_ROLE,
            "ssm:GetParameter",
            f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter{name}",
            values,
        )
    }

    assert f"{PARAMETER_PATH_PREFIX}/database-url" in names
    assert readable == {substitute(name, prefix) for name in app.gated_secrets()}
    assert not any(
        statement.allows("kms:Decrypt") for statement in _oidc().role_statements(GITHUB_ROLE)
    )


def test_the_github_role_can_read_only_the_application_queue_attributes() -> None:
    """verify-staging-queue-wiring compares each deployed queue's settings with the template."""
    app = template_model()
    environment = {"Environment": app.parameter_definitions()["Environment"].default}
    queues = [
        substitute(name, environment)
        for queue in app.queues().values()
        for name in possible_strings(queue.properties["QueueName"])
    ]
    values = _values()

    assert len(queues) == len(app.queues())
    for queue in queues:
        arn = f"arn:aws:sqs:{REGION}:{ACCOUNT}:{queue}"
        assert _can(GITHUB_ROLE, "sqs:GetQueueAttributes", arn, values), queue
        for action in (
            "sqs:ReceiveMessage",
            "sqs:SendMessage",
            "sqs:DeleteMessage",
            "sqs:PurgeQueue",
            "sqs:SetQueueAttributes",
        ):
            assert not _can(GITHUB_ROLE, action, arn, values), (action, queue)
    other = f"arn:aws:sqs:{REGION}:{ACCOUNT}:other-queue"
    assert not _can(GITHUB_ROLE, "sqs:GetQueueAttributes", other, values)


def test_the_github_role_can_publish_the_frontend_but_not_touch_raw_documents() -> None:
    """deploy-staging, publish-staging-frontend and rollback-staging-frontend sync the site.

    Each then clears the CloudFront cache.
    """
    app = template_model()
    names = {
        "Environment": app.parameter_definitions()["Environment"].default,
        "AWS::AccountId": ACCOUNT,
    }

    def bucket(logical_id: str) -> str:
        [name] = possible_strings(app.properties(logical_id)["BucketName"])
        return f"arn:aws:s3:::{substitute(name, names)}"

    frontend, raw = bucket("FrontendBucket"), bucket("RawDocumentBucket")
    distribution = f"arn:aws:cloudfront::{ACCOUNT}:distribution/E1EXAMPLE"
    values = _values()

    for action in ("s3:ListBucket", "s3:GetBucketLocation"):
        assert _can(GITHUB_ROLE, action, frontend, values), action
        assert not _can(GITHUB_ROLE, action, raw, values), action
    for action in ("s3:GetObject", "s3:PutObject", "s3:DeleteObject"):
        assert _can(GITHUB_ROLE, action, f"{frontend}/index.html", values), action
        assert not _can(GITHUB_ROLE, action, f"{raw}/raw/announcement.pdf", values), action
    assert _can(GITHUB_ROLE, "cloudfront:CreateInvalidation", distribution, values)


def test_the_execution_role_can_change_and_confirm_the_custom_domain_records() -> None:
    """CloudFormation writes the site's Route 53 records, then polls each change until it is done.

    DnsHostedZoneId stays "*" until the OIDC stack is redeployed with the site's zone.
    """
    zone = "Z0EXAMPLE"

    assert template_model().of_type("AWS::Route53::RecordSetGroup")
    for values in (_values(), _values(DnsHostedZoneId=zone)):
        for action in (
            "route53:ChangeResourceRecordSets",
            "route53:GetHostedZone",
            "route53:ListResourceRecordSets",
        ):
            assert _can(
                EXECUTION_ROLE, action, f"arn:aws:route53:::hostedzone/{zone}", values
            ), action
        assert _can(
            EXECUTION_ROLE, "route53:GetChange", "arn:aws:route53:::change/C0EXAMPLE", values
        )


def test_the_release_module_deploys_through_the_execution_role() -> None:
    """plan passes --role-arn with CLOUDFORMATION_ROLE_NAME, and only CloudFormation may use it."""
    execution = _oidc().properties(EXECUTION_ROLE)
    [trust] = execution["AssumeRolePolicyDocument"]["Statement"]

    assert execution["RoleName"] == CLOUDFORMATION_ROLE_NAME
    assert trust["Principal"] == {"Service": "cloudformation.amazonaws.com"}
    assert trust["Action"] == "sts:AssumeRole"
