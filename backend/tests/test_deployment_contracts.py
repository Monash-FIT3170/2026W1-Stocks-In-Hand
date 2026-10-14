import re
from collections.abc import Callable
from pathlib import Path

import yaml

from tools import sync_tickers
from tools.template_model import possible_strings, template_model

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"


def test_ticker_list_copies_match_the_catalogue() -> None:
    """The frontend pages, CloudFront route and schedule defaults follow app.sources."""
    stale = sync_tickers.stale_copies()

    assert not stale, (
        "Run `python -m tools.sync_tickers` in backend/ to update:\n" + "\n".join(stale)
    )


def test_ticker_sync_rewrites_a_stale_copy(tmp_path: Path) -> None:
    for relative in (
        sync_tickers.FRONTEND_TICKERS,
        sync_tickers.TEMPLATE,
        sync_tickers.DEPLOY_WORKFLOW,
    ):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(
            (REPOSITORY_ROOT / relative).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    template = tmp_path / sync_tickers.TEMPLATE
    template.write_text(
        template.read_text(encoding="utf-8").replace("|WDS|WES)", "|WDS)"),
        encoding="utf-8",
    )

    [stale] = sync_tickers.stale_copies(tmp_path)
    assert "CloudFront ticker route" in stale
    assert sync_tickers.write_copies(tmp_path) == [sync_tickers.TEMPLATE]
    assert sync_tickers.stale_copies(tmp_path) == []
    assert template.read_text(encoding="utf-8") == (
        REPOSITORY_ROOT / sync_tickers.TEMPLATE
    ).read_text(encoding="utf-8")


def test_local_backend_installs_cognito_jwt_dependency() -> None:
    requirements = (
        REPOSITORY_ROOT / "backend" / "requirements-api.txt"
    ).read_text(encoding="utf-8")

    assert "PyJWT[crypto]==2.13.0" in requirements.splitlines()


def test_api_image_does_not_own_finbert_inference() -> None:
    dockerfile = (REPOSITORY_ROOT / "backend" / "Dockerfile.api").read_text(encoding="utf-8")
    route = (
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "api"
        / "routes"
        / "category_sentiment.py"
    ).read_text(encoding="utf-8")

    assert "requirements-analysis.txt" not in dockerfile
    assert "transformers" not in dockerfile
    assert '@router.get("/{ticker}"' in route
    assert "return read_ticker_category_sentiment(" in route
    assert "On-demand FinBERT inference is not available in the API runtime" in route


def test_analysis_image_keeps_finbert_out_of_lambda_opt_mount() -> None:
    dockerfile = (
        REPOSITORY_ROOT / "backend" / "Dockerfile.analysis"
    ).read_text(encoding="utf-8")

    assert "FINBERT_MODEL=/var/task/models/finbert" in dockerfile
    assert "save_pretrained('/var/task/models/finbert')" in dockerfile
    assert "chmod -R a+rX /var/task/models/finbert" in dockerfile
    assert 'model.safetensors)\" = \"644\"' in dockerfile
    assert "/opt/finbert" not in dockerfile


def test_cloudfront_routes_unknown_pages_to_exported_404() -> None:
    model = template_model()
    route_code = model.properties("FrontendRouteFunction")["FunctionCode"]
    response_code = model.properties("FrontendResponseFunction")["FunctionCode"]
    associations = model.properties("FrontendDistribution")["DistributionConfig"][
        "DefaultCacheBehavior"
    ]["FunctionAssociations"]

    assert "request.uri = '/404.html'" in route_code
    assert "x-stonks-not-found" in route_code
    assert "response.statusCode = 404" in response_code
    assert {
        "EventType": "viewer-response",
        "FunctionARN": {"Fn::GetAtt": ["FrontendResponseFunction", "FunctionARN"]},
    } in associations


def test_cloudfront_allows_every_exported_static_page() -> None:
    """Every non-dynamic frontend page must survive the viewer-request rewrite."""
    route_code = template_model().properties("FrontendRouteFunction")["FunctionCode"]
    routes_block = route_code.split("var staticRoutes = {", 1)[1].split("};", 1)[0]
    configured_routes = set(re.findall(r"'([^']+)': true", routes_block))

    app_root = REPOSITORY_ROOT / "frontend" / "src" / "app"
    source_routes = set()
    for page in app_root.rglob("page.jsx"):
        relative_parent = page.relative_to(app_root).parent
        if any(part.startswith("[") for part in relative_parent.parts):
            continue
        route = "/" if relative_parent == Path(".") else f"/{relative_parent.as_posix()}"
        source_routes.add(route)

    assert source_routes <= configured_routes, (
        "CloudFront staticRoutes is missing exported pages: "
        f"{sorted(source_routes - configured_routes)}"
    )


def test_brevo_notification_infrastructure_contract() -> None:
    """Notification infrastructure must stay disabled, scoped, and retry-safe.

    Queue, dead-letter, alarm, output and grant wiring are checked for every
    queue by the rules in test_queue_wiring.py.
    """
    model = template_model()
    api = model.function("ApiFunction")
    analysis = model.function("AnalysisFunction")
    notification = model.function("NotificationFunction")
    brevo_key = {
        "Fn::If": [
            "IsNotificationsEnabled",
            {"Fn::Sub": "${ParameterPathPrefix}/brevo-api-key"},
            "",
        ]
    }

    assert model.parameters["NotificationsEnabled"]["Default"] == "false"
    assert model.document["Conditions"]["IsNotificationsEnabled"] == {
        "Fn::Equals": [{"Ref": "NotificationsEnabled"}, "true"]
    }
    assert "AlertSenderRequiredWhenNotificationsEnabled" in model.document["Rules"]

    for function in (api, notification):
        assert function.environment["NOTIFICATIONS_ENABLED"] == {"Ref": "NotificationsEnabled"}
        assert function.environment["ALERT_SENDER_EMAIL"] == {"Ref": "AlertSenderEmail"}
        assert function.environment["BREVO_API_KEY_PARAMETER"] == brevo_key
        assert function.environment["FRONTEND_BASE_URL"] == {"Ref": "FrontendBaseUrl"}
    for function in model.functions().values():
        assert not any(
            action.lower().startswith("ses:")
            for statement in function.statements
            for action in statement.actions
        ), function.logical_id

    assert analysis.environment["NOTIFICATIONS_ENABLED"] == {"Ref": "NotificationsEnabled"}
    [enqueue] = [s for s in analysis.statements if s.sid == "EnqueueNotifications"]
    assert enqueue.condition == "IsNotificationsEnabled"

    assert notification.properties["ImageUri"] == {"Ref": "ApiImageUri"}
    assert notification.properties["ImageConfig"]["Command"] == ["lambdas.notify.handler"]
    assert "ReservedConcurrentExecutions" not in notification.properties
    assert notification.environment["ALERT_DAILY_BUDGET"] == {"Ref": "AlertDailyBudget"}
    assert notification.environment["ALERT_MAX_PER_INVESTOR_PER_RUN"] == {
        "Ref": "AlertMaxPerInvestorPerRun"
    }
    assert "NotificationLogGroup" in model.resources


def test_github_oidc_can_check_brevo_parameter_metadata() -> None:
    """The prepare role may inspect the Brevo parameter without decrypting it."""
    template = (REPOSITORY_ROOT / "infra" / "github-oidc.yaml").read_text(
        encoding="utf-8"
    )

    assert "Sid: ReadBrevoParameterMetadata" in template
    assert "Action: ssm:GetParameter" in template
    assert (
        "parameter/stocks-in-hand/staging/brevo-api-key" in template
    )


def test_cloudformation_role_can_poll_route53_dns_changes() -> None:
    """CloudFormation must be able to confirm Route 53 record changes."""
    template = (REPOSITORY_ROOT / "infra" / "github-oidc.yaml").read_text(
        encoding="utf-8"
    )
    statement = template.split("- Sid: ReadDnsChangeStatus", 1)[1].split(
        "- Sid:", 1
    )[0]

    assert "Action: route53:GetChange" in statement
    assert 'Resource: !Sub "arn:${AWS::Partition}:route53:::change/*"' in statement
    assert "hostedzone/" not in statement


def test_custom_domain_certificate_parameter_is_lint_constrained() -> None:
    """SAM lint must know that the optional certificate value is an ACM ARN."""
    model = template_model()
    certificate_parameter = model.parameters["SiteCertificateArn"]
    lint_config = model.resource("FrontendDistribution")["Metadata"]["cfn-lint"]["config"]

    assert "arn:aws[a-zA-Z-]*:acm:us-east-1:" in certificate_parameter["AllowedPattern"]
    assert "CustomDomainValuesRequiredTogether" in model.document["Rules"]
    assert "W1030" in lint_config["ignore_checks"]


def test_bedrock_provider_is_bounded_and_iam_scoped() -> None:
    """Bedrock must be opt-in, model-scoped, and free of Groq secrets."""
    model = template_model()
    api = model.function("ApiFunction")
    analysis = model.function("AnalysisFunction")

    assert model.parameters["BedrockEnabled"]["Default"] == "false"
    for function in (api, analysis):
        environment = function.environment
        assert environment["LLM_PROVIDER"] == "bedrock"
        assert environment["BEDROCK_ENABLED"] == {"Ref": "BedrockEnabled"}
        assert environment["BEDROCK_MODEL_ID"] == "openai.gpt-oss-120b-1:0"
        assert environment["BEDROCK_MAX_PROMPT_CHARS"] == "30000"
        # Each summary kind sets its own output budget. A per-function budget
        # let the admin routes truncate summaries the worker completed.
        assert "BEDROCK_MAX_OUTPUT_TOKENS" not in environment
        assert "GROQ_API_KEY_PARAMETER" not in environment

        bedrock = [s for s in function.statements if s.allows("bedrock:InvokeModel")]
        assert [s.condition for s in bedrock] == ["IsBedrockEnabled"]
        assert bedrock[0].actions == ("bedrock:InvokeModel",)
        [resource] = bedrock[0].resources
        assert possible_strings(resource)[0].endswith(
            "::foundation-model/openai.gpt-oss-120b-1:0"
        )

    assert api.environment["BEDROCK_SERVICE_TIER"] == "default"
    assert analysis.environment["BEDROCK_SERVICE_TIER"] == "flex"

    runtime_requirements = (
        REPOSITORY_ROOT / "backend" / "requirements-api.txt"
    ).read_text(encoding="utf-8")
    assert "groq==" not in runtime_requirements.lower()


def test_legacy_release_retains_cognito_foundation() -> None:
    """The legacy-auth release keeps the Cognito pool and client deployed."""
    model = template_model()

    for logical_id in ("CognitoUserPool", "CognitoUserPoolClient"):
        resource = model.resource(logical_id)
        assert resource["DeletionPolicy"] == "Retain", logical_id
        assert resource["UpdateReplacePolicy"] == "Retain", logical_id
    assert model.outputs_referencing("CognitoUserPool") == ["CognitoUserPoolId"]
    assert model.outputs_referencing("CognitoUserPoolClient") == ["CognitoUserPoolClientId"]


def test_frontend_uses_read_only_sentiment_contract() -> None:
    api = (
        REPOSITORY_ROOT / "frontend" / "src" / "app" / "lib" / "api.js"
    ).read_text(encoding="utf-8")

    sentiment_function = api.split("export async function fetchTickerCategorySentiment", 1)[1]
    assert "fetchJsonCoalesced" in sentiment_function
    assert 'method: "POST"' not in sentiment_function.split("}", 1)[0]
    assert "persist=false" not in sentiment_function


def test_public_discussion_schedule_is_bounded_and_disabled_by_default() -> None:
    model = template_model()
    function = model.function("PublicDiscussionSchedulerFunction")
    schedule = model.properties("WeekdayPublicDiscussionSchedule")
    dockerfile = (REPOSITORY_ROOT / "backend" / "Dockerfile.api").read_text(
        encoding="utf-8"
    )

    assert model.parameters["PublicDiscussionScheduleEnabled"]["Default"] == "false"
    assert "ReservedConcurrentExecutions" not in function.properties
    assert function.environment["PUBLIC_DISCUSSION_PER_SOURCE_LIMIT"] == {
        "Ref": "PublicDiscussionPerSourceLimit"
    }
    assert schedule["State"] == {
        "Fn::If": ["IsPublicDiscussionScheduleEnabled", "ENABLED", "DISABLED"]
    }
    assert schedule["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 2
    assert "lambdas/public_discussion_schedule.py" in dockerfile


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _steps(name: str) -> list[dict]:
    return [
        step for job in _workflow(name)["jobs"].values() for step in job.get("steps") or []
    ]


def test_release_workflows_never_build_sam_deploy_themselves() -> None:
    """Only tools/release.py knows the parameters and the image repositories."""
    builders = {
        path.name
        for path in WORKFLOWS.glob("*.yml")
        for step in _steps(path.name)
        if any(
            text in step.get("run", "")
            for text in ("sam deploy", "--parameter-overrides", "--image-repositories")
        )
    }

    assert builders == set()


def test_workflows_read_stack_parameters_and_outputs_through_the_release_module() -> None:
    queries = {
        (path.name, step["name"])
        for path in WORKFLOWS.glob("*.yml")
        for step in _steps(path.name)
        if "describe-stacks" in step.get("run", "")
    }
    # These check out an older release, or nothing, so tools.release may not be there.
    frontend = {"publish-staging-frontend.yml", "rollback-staging-frontend.yml"}

    assert {(name, step) for name, step in queries if name not in frontend} == {
        # The stack status picks the waiter, and the whole output table is evidence.
        ("execute-staging-change-set.yml", "Verify the approved change set"),
        ("execute-staging-change-set.yml", "Record deployment outputs"),
    }


def test_approved_main_merges_plan_build_deploy_and_check_health_in_order() -> None:
    workflow = _workflow("deploy-staging.yml")
    [job] = workflow["jobs"].values()
    steps = job["steps"]

    def position(found: Callable[[dict], bool]) -> list[int]:
        return [index for index, step in enumerate(steps) if found(step)]

    [plan] = position(lambda step: step.get("id") == "release")
    builds = position(lambda step: step.get("uses", "").startswith("docker/build-push-action"))
    [deploy] = position(lambda step: "tools.release apply" in step.get("run", ""))
    [health] = position(lambda step: step.get("id") == "health")
    [rollback] = position(
        lambda step: "prepare-staging-backend-rollback.yml" in step.get("run", "")
    )
    [publish] = position(lambda step: "cloudfront create-invalidation" in step.get("run", ""))

    # PyYAML reads the "on" key as True.
    assert workflow[True]["push"]["branches"] == ["main"]
    assert job["environment"] == "staging"
    assert workflow["concurrency"] == {
        "group": "stocks-in-hand-staging-deploy",
        "cancel-in-progress": False,
    }
    assert "python -m tools.release plan" in steps[plan]["run"]
    # A manual run only creates a change set for review.
    assert steps[plan]["env"]["DEPLOY_MODE"] == (
        "${{ github.event_name == 'workflow_dispatch' && '--no-execute' || '--execute' }}"
    )
    assert len(builds) == 3
    assert plan < min(builds) and max(builds) < deploy
    assert "scripts/wait_for_health.py" in steps[health]["run"]
    assert deploy < health < rollback
    assert "steps.release.outputs.previous_release_sha != ''" in steps[rollback]["if"]
    assert steps[rollback]["env"]["PREVIOUS_RELEASE_SHA"] == (
        "${{ steps.release.outputs.previous_release_sha }}"
    )
    # The frontend is published only once the deployed API is healthy.
    assert health < publish


def test_every_manual_deploy_input_reaches_the_release_plan() -> None:
    workflow = _workflow("deploy-staging.yml")
    [plan] = [step for step in _steps("deploy-staging.yml") if step.get("id") == "release"]
    passed = {
        name
        for name in workflow[True]["workflow_dispatch"]["inputs"]
        if any(f"inputs.{name} ||" in value for value in plan["env"].values())
    }

    assert passed == set(workflow[True]["workflow_dispatch"]["inputs"])


def test_rollback_plans_through_the_release_module_then_applies() -> None:
    [step] = [
        step
        for step in _steps("prepare-staging-backend-rollback.yml")
        if "tools.release" in step.get("run", "")
    ]
    run = step["run"]

    assert step["working-directory"] == "backend"
    assert "python -m tools.release plan --rollback --no-execute" in run
    assert run.index("tools.release plan") < run.index("python -m tools.release apply")


def test_ci_reproduces_the_deployed_schema_drift_from_one_script() -> None:
    """a7dd2c6 changed two inline copies of the drift and missed the third."""
    steps = [(path.name, step) for path in WORKFLOWS.glob("*.yml") for step in _steps(path.name)]
    script = {
        name
        for name, step in steps
        if "python -m scripts.reproduce_deployed_schema_drift" in step.get("run", "")
        and step.get("working-directory") == "backend"
    }
    inline = {
        name
        for name, step in steps
        if any(text in step.get("run", "") for text in ("DROP COLUMN", "alembic upgrade"))
    }

    assert script == {"deploy-staging.yml", "validate-branch.yml", "validate-staging-release.yml"}
    assert inline == set()


def test_feature_switches_default_to_off() -> None:
    switches = {
        name: parameter["Default"]
        for name, parameter in template_model().parameters.items()
        if sorted(parameter.get("AllowedValues", [])) == ["false", "true"]
    }

    assert {"NotificationsEnabled", "PublicDiscussionScheduleEnabled"} <= set(switches)
    # AnalysisEnabled is a kill switch for work already paid for, so it is on.
    assert {name for name, default in switches.items() if default != "false"} == {
        "AnalysisEnabled"
    }


def test_marketaux_is_ssm_backed_bounded_and_release_gated() -> None:
    model = template_model()
    oidc = (REPOSITORY_ROOT / "infra" / "github-oidc.yaml").read_text(
        encoding="utf-8"
    )
    marketaux_token = {
        "Fn::If": [
            "IsMarketauxEnabled",
            {"Fn::Sub": "${ParameterPathPrefix}/marketaux-api-token"},
            "",
        ]
    }
    scheduler = model.function("SchedulerFunction")

    assert model.parameters["MarketauxEnabled"]["Default"] == "false"
    assert model.parameters["MarketauxPerTickerLimit"]["MaxValue"] == 25
    for function_id in ("ApiFunction", "SchedulerFunction"):
        environment = model.function(function_id).environment
        assert environment["MARKETAUX_API_TOKEN_PARAMETER"] == marketaux_token, function_id
    assert scheduler.environment["MARKETAUX_ENABLED"] == {"Ref": "MarketauxEnabled"}
    assert scheduler.environment["MARKETAUX_PER_TICKER_LIMIT"] == {
        "Ref": "MarketauxPerTickerLimit"
    }

    assert "Sid: ReadMarketauxParameterMetadata" in oidc
    assert "parameter/stocks-in-hand/staging/marketaux-api-token" in oidc


def test_staging_validation_workflow_cannot_deploy() -> None:
    validation = (
        REPOSITORY_ROOT
        / ".github"
        / "workflows"
        / "validate-staging-release.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in validation
    assert "sam validate --lint" in validation
    assert "Dockerfile.api" in validation
    assert "Dockerfile.scraper" in validation
    assert "Dockerfile.analysis" in validation
    assert "push: false" in validation
    assert "environment: staging" not in validation
    assert "configure-aws-credentials" not in validation
    assert "sam deploy" not in validation
    assert "docker login" not in validation
