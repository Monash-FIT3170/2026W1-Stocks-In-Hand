from pathlib import Path

from app.sources import SOURCES

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_all_canonical_tickers_are_deployable_but_schedule_stays_conservative() -> None:
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(
        encoding="utf-8"
    )
    expected = "ANZ,BHP,CBA,COH,COL,CSL,MQG,ORG,RIO,TCL,TLS,WDS,WES"

    assert set(SOURCES) == set(expected.split(","))
    assert f"SUPPORTED_TICKERS: {expected}" in template
    scheduled_parameter = template.split("  ScheduledTickers:", 1)[1].split(
        "  ScheduledPublicDiscussionSources:", 1
    )[0]
    assert "Default: ANZ,BHP,CBA,CSL,WES" in scheduled_parameter

    ticker_layout = (
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "app"
        / "ticker"
        / "[symbol]"
        / "layout.jsx"
    ).read_text(encoding="utf-8")
    deployed_list = ticker_layout.split("const DEPLOYED_TICKERS = [", 1)[1].split(
        "]", 1
    )[0]
    for ticker in SOURCES:
        assert f'"{ticker}"' in deployed_list

    cloudfront_ticker_pattern = template.split("var tickerRoute = ", 1)[1].split(
        ";", 1
    )[0]
    for ticker in SOURCES:
        assert ticker in cloudfront_ticker_pattern


def test_local_backend_installs_cognito_jwt_dependency() -> None:
    requirements = (
        REPOSITORY_ROOT / "backend" / "requirements.txt"
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
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(encoding="utf-8")

    assert "request.uri = '/404.html'" in template
    assert "x-stonks-not-found" in template
    assert "response.statusCode = 404" in template
    assert "EventType: viewer-response" in template


def test_brevo_notification_infrastructure_contract() -> None:
    """Notification infrastructure must stay disabled, scoped, and retry-safe."""
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(
        encoding="utf-8"
    )

    api_function = template.split("  ApiFunction:", 1)[1].split(
        "  DiscoveryFunction:", 1
    )[0]
    analysis_function = template.split("  AnalysisFunction:", 1)[1].split(
        "  NotificationFunction:", 1
    )[0]
    notification_function = template.split("  NotificationFunction:", 1)[1].split(
        "  SchedulerFunction:", 1
    )[0]
    notification_queue = template.split("  NotificationQueue:", 1)[1].split(
        "  AnalysisQueuePolicy:", 1
    )[0]
    notification_alarm = template.split("  NotificationDlqAlarm:", 1)[1].split(
        "  FrontendOriginAccessControl:", 1
    )[0]

    assert 'NotificationsEnabled:' in template
    assert 'Default: "false"' in template.split("  NotificationsEnabled:", 1)[1]
    assert (
        'IsNotificationsEnabled: !Equals [!Ref NotificationsEnabled, "true"]'
        in template
    )
    assert "AlertSenderRequiredWhenNotificationsEnabled:" in template
    assert "NotificationDeadLetterQueue:" in template
    assert "Type: AWS::SQS::Queue" in notification_queue
    assert "VisibilityTimeout: 1800" in notification_queue
    assert (
        "deadLetterTargetArn: !GetAtt NotificationDeadLetterQueue.Arn"
        in notification_queue
    )
    assert "maxReceiveCount: 5" in notification_queue

    assert "NOTIFICATIONS_ENABLED: !Ref NotificationsEnabled" in api_function
    assert "ALERT_SENDER_EMAIL: !Ref AlertSenderEmail" in api_function
    assert "BREVO_API_KEY_PARAMETER: !If" in api_function
    assert "${ParameterPathPrefix}/brevo-api-key" in api_function
    assert "- IsNotificationsEnabled" in api_function
    assert (
        "FRONTEND_BASE_URL: !Ref FrontendBaseUrl"
        in api_function
    )
    assert "ses:" not in api_function.lower()

    assert (
        "NOTIFICATIONS_ENABLED: !Ref NotificationsEnabled" in analysis_function
    )
    assert "NOTIFICATION_QUEUE_URL: !Ref NotificationQueue" in analysis_function
    assert "Sid: EnqueueNotifications" in analysis_function
    assert "Resource: !GetAtt NotificationQueue.Arn" in analysis_function
    assert "- IsNotificationsEnabled" in analysis_function

    assert "ImageUri: !Ref ApiImageUri" in notification_function
    assert "lambdas.notify.handler" in notification_function
    assert "ReservedConcurrentExecutions" not in notification_function
    assert "ALERT_DAILY_BUDGET: !Ref AlertDailyBudget" in notification_function
    assert (
        "ALERT_MAX_PER_INVESTOR_PER_RUN: !Ref AlertMaxPerInvestorPerRun"
        in notification_function
    )
    assert (
        "FRONTEND_BASE_URL: !Ref FrontendBaseUrl"
        in notification_function
    )
    assert "BREVO_API_KEY_PARAMETER: !If" in notification_function
    assert "${ParameterPathPrefix}/brevo-api-key" in notification_function
    assert "Sid: ReadNotificationParameters" in notification_function
    assert "ssm:GetParameter" in notification_function
    assert "ses:" not in notification_function.lower()
    assert "- IsNotificationsEnabled" in notification_function
    assert "BatchSize: 10" in notification_function
    assert (
        "Enabled: !If [IsNotificationsEnabled, true, false]"
        in notification_function
    )
    assert "ReportBatchItemFailures" in notification_function

    assert "NotificationLogGroup:" in template
    assert "AlarmActions:" in notification_alarm
    assert "!Ref AlarmTopic" in notification_alarm
    assert "NotificationQueueUrl:" in template
    assert "NotificationDeadLetterQueueUrl:" in template


def test_staging_workflow_wires_brevo_notification_parameters() -> None:
    """Every change set must carry the notification release controls."""
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "deploy-staging.yml"
    ).read_text(encoding="utf-8")

    assert "enable_notifications:" in workflow
    notification_input = workflow.split("      enable_notifications:", 1)[1].split(
        "      enable_bedrock:", 1
    )[0]
    assert 'default: "false"' in notification_input
    assert (
        '--image-repositories "NotificationFunction=$ECR_REGISTRY/'
        'stocks-in-hand-api"' in workflow
    )
    assert '"NotificationsEnabled=$ENABLE_NOTIFICATIONS"' in workflow
    assert '"AlertSenderEmail=${{ vars.ALERT_SENDER_EMAIL }}"' in workflow
    assert "AUTO_DEPLOY_ENABLE_NOTIFICATIONS" in workflow
    assert "Validate Brevo notification prerequisites" in workflow
    preflight = workflow.split(
        "      - name: Validate Brevo notification prerequisites", 1
    )[1].split("      - name:", 1)[0]
    assert "if: env.ENABLE_NOTIFICATIONS == 'true'" in preflight
    assert 'ALERT_SENDER_EMAIL: ${{ vars.ALERT_SENDER_EMAIL }}' in preflight
    assert '"$PARAMETER_PATH_PREFIX/brevo-api-key"' in preflight
    assert "aws ssm get-parameter" in preflight
    assert "Parameter.Type" in preflight
    assert '"$PARAMETER_TYPE" != "SecureString"' in preflight


def test_approved_main_merges_deploy_backend_and_frontend_automatically() -> None:
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "deploy-staging.yml"
    ).read_text(encoding="utf-8")

    assert "name: Deploy staging release" in workflow
    assert "  push:\n    branches:\n      - main" in workflow
    assert "environment: staging" in workflow
    assert "group: stocks-in-hand-staging-deploy" in workflow
    assert "cancel-in-progress: false" in workflow

    configuration = workflow.split(
        "      - name: Resolve deployment configuration", 1
    )[1].split("      - name:", 1)[0]
    assert "read_stack_parameter" in configuration
    assert "AUTO_DEPLOY_AUTH_PROVIDER" in configuration
    assert "AUTO_DEPLOY_ENABLE_SCHEDULE" in configuration
    assert "AUTO_DEPLOY_ENABLE_BEDROCK" in configuration
    assert (
        'if [ "$GITHUB_EVENT_NAME" = "workflow_dispatch" ]'
        in configuration
    )

    deployment = workflow.split(
        "      - name: Create or execute the SAM change set", 1
    )[1].split("      - name:", 1)[0]
    assert "sam deploy" in deployment
    assert "DEPLOY_MODE_ARGS+=(--no-execute-changeset)" in deployment
    assert '"${DEPLOY_MODE_ARGS[@]}"' in deployment
    assert (
        '"ApiImageUri=$ECR_REGISTRY/stocks-in-hand-api:$RELEASE_SHA"'
        in deployment
    )

    assert (
        "Wait for the automatically deployed API to report healthy"
        in workflow
    )
    assert "backend/scripts/wait_for_health.py" in workflow
    assert (
        "Prepare rollback after an automatic health-check failure"
        in workflow
    )
    assert "Build the deployed frontend configuration" in workflow
    assert "Preserve the automatic frontend release snapshot" in workflow
    assert "Publish the automatic frontend release" in workflow
    assert "aws cloudfront create-invalidation" in workflow


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


def test_custom_domain_certificate_parameter_is_lint_constrained() -> None:
    """SAM lint must know that the optional certificate value is an ACM ARN."""
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(
        encoding="utf-8"
    )
    certificate_parameter = template.split("  SiteCertificateArn:", 1)[1].split(
        "  SiteHostedZoneId:", 1
    )[0]

    assert "AllowedPattern:" in certificate_parameter
    assert "arn:aws[a-zA-Z-]*:acm:us-east-1:" in certificate_parameter
    assert "CustomDomainValuesRequiredTogether:" in template
    distribution = template.split("  FrontendDistribution:", 1)[1].split(
        "  FrontendBucketPolicy:", 1
    )[0]
    assert "ignore_checks:" in distribution
    assert "- W1030" in distribution


def test_bedrock_provider_is_bounded_and_iam_scoped() -> None:
    """Bedrock must be opt-in, model-scoped, and free of Groq secrets."""
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(
        encoding="utf-8"
    )
    api_function = template.split("  ApiFunction:", 1)[1].split(
        "  DiscoveryFunction:", 1
    )[0]
    analysis_function = template.split("  AnalysisFunction:", 1)[1].split(
        "  NotificationFunction:", 1
    )[0]

    assert 'Default: "false"' in template.split("  BedrockEnabled:", 1)[1]
    for function in (api_function, analysis_function):
        assert "LLM_PROVIDER: bedrock" in function
        assert "BEDROCK_ENABLED: !Ref BedrockEnabled" in function
        assert "BEDROCK_MODEL_ID: openai.gpt-oss-120b-1:0" in function
        assert 'BEDROCK_MAX_PROMPT_CHARS: "30000"' in function
        assert "- IsBedrockEnabled" in function
        assert "Action: bedrock:InvokeModel" in function
        assert (
            "foundation-model/openai.gpt-oss-120b-1:0"
            in function
        )
        assert "GROQ_API_KEY_PARAMETER" not in function
        assert "bedrock:CountTokens" not in function

    assert "BEDROCK_SERVICE_TIER: default" in api_function
    assert "BEDROCK_SERVICE_TIER: flex" in analysis_function
    assert 'BEDROCK_MAX_OUTPUT_TOKENS: "1024"' in api_function
    assert 'BEDROCK_MAX_OUTPUT_TOKENS: "4096"' in analysis_function

    runtime_requirements = (
        REPOSITORY_ROOT / "backend" / "requirements-api.txt"
    ).read_text(encoding="utf-8")
    assert "groq==" not in runtime_requirements.lower()


def test_legacy_release_retains_cognito_foundation() -> None:
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(encoding="utf-8")

    user_pool = template.split("  CognitoUserPool:", 1)[1].split(
        "  CognitoUserPoolClient:", 1
    )[0]
    app_client = template.split("  CognitoUserPoolClient:", 1)[1].split(
        "  ServerlessHttpApi:", 1
    )[0]

    assert "Type: AWS::Cognito::UserPool" in user_pool
    assert "DeletionPolicy: Retain" in user_pool
    assert "UpdateReplacePolicy: Retain" in user_pool
    assert "DeletionProtection: ACTIVE" in user_pool

    assert "Type: AWS::Cognito::UserPoolClient" in app_client
    assert "DeletionPolicy: Retain" in app_client
    assert "UpdateReplacePolicy: Retain" in app_client
    assert "GenerateSecret: false" in app_client
    assert "CognitoUserPoolId:" in template
    assert "CognitoUserPoolClientId:" in template


def test_frontend_uses_read_only_sentiment_contract() -> None:
    api = (
        REPOSITORY_ROOT / "frontend" / "src" / "app" / "lib" / "api.js"
    ).read_text(encoding="utf-8")

    sentiment_function = api.split("export async function fetchTickerCategorySentiment", 1)[1]
    assert "fetchJsonCoalesced" in sentiment_function
    assert 'method: "POST"' not in sentiment_function.split("}", 1)[0]
    assert "persist=false" not in sentiment_function


def test_public_discussion_schedule_is_bounded_and_disabled_by_default() -> None:
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(
        encoding="utf-8"
    )
    dockerfile = (REPOSITORY_ROOT / "backend" / "Dockerfile.api").read_text(
        encoding="utf-8"
    )

    parameter = template.split("  PublicDiscussionScheduleEnabled:", 1)[1].split(
        "  AnalysisEnabled:", 1
    )[0]
    function = template.split("  PublicDiscussionSchedulerFunction:", 1)[1].split(
        "  SchedulerInvokeRole:", 1
    )[0]

    assert 'Default: "false"' in parameter
    assert "ReservedConcurrentExecutions" not in function
    assert "PublicDiscussionPerSourceLimit" in function
    assert "MaximumRetryAttempts: 2" in template
    assert "lambdas/public_discussion_schedule.py" in dockerfile


def test_release_workflows_keep_public_discussion_schedule_explicit() -> None:
    deploy = (
        REPOSITORY_ROOT / ".github" / "workflows" / "deploy-staging.yml"
    ).read_text(encoding="utf-8")
    rollback = (
        REPOSITORY_ROOT
        / ".github"
        / "workflows"
        / "prepare-staging-backend-rollback.yml"
    ).read_text(encoding="utf-8")

    assert "enable_public_discussion_schedule:" in deploy
    assert "PublicDiscussionSchedulerFunction=" in deploy
    assert "PublicDiscussionPerSourceLimit=" in deploy
    assert "OutputKey=='FrontendUrl'" in deploy
    assert '"FrontendBaseUrl=$FRONTEND_BASE_URL"' in deploy
    assert '"PublicDiscussionScheduleEnabled=false"' in rollback
    assert "PublicDiscussionSchedulerFunction=" in rollback
    assert "OutputKey=='FrontendUrl'" in rollback
    assert '"FrontendBaseUrl=$FRONTEND_BASE_URL"' in rollback


def test_marketaux_is_ssm_backed_bounded_and_release_gated() -> None:
    template = (REPOSITORY_ROOT / "infra" / "template.yaml").read_text(
        encoding="utf-8"
    )
    workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "deploy-staging.yml"
    ).read_text(encoding="utf-8")
    oidc = (REPOSITORY_ROOT / "infra" / "github-oidc.yaml").read_text(
        encoding="utf-8"
    )
    api_function = template.split("  ApiFunction:", 1)[1].split(
        "  DiscoveryFunction:", 1
    )[0]
    scheduler_function = template.split("  SchedulerFunction:", 1)[1].split(
        "  PublicDiscussionSchedulerFunction:", 1
    )[0]

    marketaux_parameter = template.split("  MarketauxEnabled:", 1)[1].split(
        "  AnalysisEnabled:", 1
    )[0]
    assert 'Default: "false"' in marketaux_parameter
    assert "MarketauxPerTickerLimit" in marketaux_parameter
    assert "MaxValue: 25" in marketaux_parameter

    for function in (api_function, scheduler_function):
        assert "MARKETAUX_API_TOKEN_PARAMETER: !If" in function
        assert "${ParameterPathPrefix}/marketaux-api-token" in function
    assert "MARKETAUX_ENABLED: !Ref MarketauxEnabled" in scheduler_function
    assert "MARKETAUX_PER_TICKER_LIMIT: !Ref MarketauxPerTickerLimit" in scheduler_function

    assert "enable_marketaux:" in workflow
    assert "AUTO_DEPLOY_ENABLE_MARKETAUX" in workflow
    assert '"MarketauxEnabled=$ENABLE_MARKETAUX"' in workflow
    assert '"MarketauxPerTickerLimit=$MARKETAUX_PER_TICKER_LIMIT"' in workflow
    preflight = workflow.split(
        "      - name: Validate Marketaux prerequisites", 1
    )[1].split("      - name:", 1)[0]
    assert "if: env.ENABLE_MARKETAUX == 'true'" in preflight
    assert '"$PARAMETER_PATH_PREFIX/marketaux-api-token"' in preflight
    assert "aws ssm get-parameter" in preflight
    assert '"$PARAMETER_TYPE" != "SecureString"' in preflight

    assert "Sid: ReadMarketauxParameterMetadata" in oidc
    assert "parameter/stocks-in-hand/staging/marketaux-api-token" in oidc


def test_infra_queue_workflow_keeps_backend_on_python_import_path() -> None:
    workflow = (
        REPOSITORY_ROOT
        / ".github"
        / "workflows"
        / "ci-infra-queue-wiring.yml"
    ).read_text(encoding="utf-8")
    command = " ".join(workflow.split())

    assert (
        "python -m pytest tests/test_queue_wiring.py "
        "tests/test_deployment_contracts.py -v"
        in command
    )


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
