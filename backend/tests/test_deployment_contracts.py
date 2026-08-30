from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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
        "FRONTEND_BASE_URL: !Sub https://${FrontendDistribution.DomainName}"
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
    assert "ReservedConcurrentExecutions: 1" in notification_function
    assert "ALERT_DAILY_BUDGET: !Ref AlertDailyBudget" in notification_function
    assert (
        "ALERT_MAX_PER_INVESTOR_PER_RUN: !Ref AlertMaxPerInvestorPerRun"
        in notification_function
    )
    assert (
        "FRONTEND_BASE_URL: !Sub https://${FrontendDistribution.DomainName}"
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
    """The reviewed change set must carry the notification release controls."""
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
    assert '"NotificationsEnabled=${{ inputs.enable_notifications }}"' in workflow
    assert '"AlertSenderEmail=${{ vars.ALERT_SENDER_EMAIL }}"' in workflow


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
    assert "ReservedConcurrentExecutions: 1" in function
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
    assert '"PublicDiscussionScheduleEnabled=false"' in rollback
    assert "PublicDiscussionSchedulerFunction=" in rollback
