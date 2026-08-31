# Staging deployment

This guide creates one staging deployment in `ap-southeast-2`. Bootstrap it
manually and leave the EventBridge schedule disabled. After the first verified
release, each approved merge to `main` validates, deploys the backend, checks
API health, publishes the frontend, and starts a CloudFront invalidation.

## Prerequisites

Install Docker, AWS CLI, AWS SAM CLI, Python, and Node.js 20. Authenticate the
AWS CLI to the intended staging account:

```bash
aws sts get-caller-identity
aws configure set region ap-southeast-2
```

Commit the exact source before building because the manual image tag is derived
from `HEAD`.

```bash
export AWS_REGION=ap-southeast-2
export OPERATIONS_EMAIL=you@example.com
export MONTHLY_BUDGET_USD=10
export BEDROCK_MONTHLY_BUDGET_USD=1
export SCHEDULED_TICKERS=ANZ,BHP,CBA,CSL,WES
export SCHEDULED_PUBLIC_DISCUSSION_SOURCES=bluesky,mastodon
export PUBLIC_DISCUSSION_PER_SOURCE_LIMIT=10
export RELEASE_SHA="$(git rev-parse HEAD)"
export AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
```

## 1. Create ECR and the budget

```bash
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name stocks-in-hand-bootstrap \
  --template-file infra/bootstrap.yaml \
  --parameter-overrides \
    "OperationsEmail=$OPERATIONS_EMAIL" \
    "MonthlyBudgetUsd=$MONTHLY_BUDGET_USD" \
    "BedrockMonthlyBudgetUsd=$BEDROCK_MONTHLY_BUDGET_USD" \
  --no-fail-on-empty-changeset
```

Open AWS Billing and Cost Management and verify that
`stocks-in-hand-monthly-cost` and `stocks-in-hand-bedrock-monthly-cost` exist
before running the pipeline. Both budgets exclude credits and refunds so the
alerts track gross usage before promotional credits run out.

The Bedrock budget is a free notification-only budget. It is not a hard cap:
AWS billing data can be delayed, so charges can pass the threshold before an
email arrives. The only zero-charge Bedrock setting is `BedrockEnabled=false`,
which leaves the analysis Lambda without permission to invoke a model.

## 2. Store runtime parameters

Use the Supabase transaction-mode pooler URL for Lambda. Enter values
interactively so they are never committed:

```bash
read -s "DATABASE_URL?Supabase runtime database URL: "
aws ssm put-parameter \
  --region "$AWS_REGION" \
  --name /stocks-in-hand/staging/database-url \
  --type SecureString \
  --value "$DATABASE_URL" \
  --overwrite
unset DATABASE_URL
```

Bedrock uses the Lambda execution role, so it does not need an API key in SSM.
When `BedrockEnabled=false`, extraction, classification, OCR, and FinBERT still
run without generated summaries.

Brevo is required only when watchlist notifications are enabled. Create an API
key in Brevo, then store it without printing or committing it:

```bash
read -s "BREVO_API_KEY?Brevo API key: "
aws ssm put-parameter \
  --region "$AWS_REGION" \
  --name /stocks-in-hand/staging/brevo-api-key \
  --type SecureString \
  --value "$BREVO_API_KEY" \
  --overwrite
unset BREVO_API_KEY
```

Verify one sender address in Brevo. Add that address as the protected GitHub
environment variable `ALERT_SENDER_EMAIL`. A custom sending domain is not
required for the first controlled staging test.

When `enable_notifications=true`, the staging preparation workflow checks that
the sender variable is non-empty and that the Brevo parameter exists as a
`SecureString`. The check reads parameter metadata only. It does not decrypt or
print the API key. Deploy the current `infra/github-oidc.yaml` first so the
GitHub role has permission to perform this check.

Reddit credentials and the blog feed allowlist are optional. Store them only
when those sources are enabled:

```bash
read -s "REDDIT_CLIENT_ID?Reddit client ID: "
aws ssm put-parameter \
  --region "$AWS_REGION" \
  --name /stocks-in-hand/staging/reddit-client-id \
  --type SecureString \
  --value "$REDDIT_CLIENT_ID" \
  --overwrite
unset REDDIT_CLIENT_ID

read -s "REDDIT_CLIENT_SECRET?Reddit client secret: "
aws ssm put-parameter \
  --region "$AWS_REGION" \
  --name /stocks-in-hand/staging/reddit-client-secret \
  --type SecureString \
  --value "$REDDIT_CLIENT_SECRET" \
  --overwrite
unset REDDIT_CLIENT_SECRET

read "PUBLIC_DISCUSSION_FEED_URLS?Comma-separated HTTPS RSS or Atom URLs: "
aws ssm put-parameter \
  --region "$AWS_REGION" \
  --name /stocks-in-hand/staging/public-discussion-feed-urls \
  --type String \
  --value "$PUBLIC_DISCUSSION_FEED_URLS" \
  --overwrite
unset PUBLIC_DISCUSSION_FEED_URLS
```

Missing Reddit parameters disable Reddit collection. A missing feed allowlist
disables blog collection. Public Bluesky and Mastodon collection need no key.

## 3. Build and push the Lambda images

```bash
aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker buildx build --platform linux/amd64 --provenance=false --load \
  -f backend/Dockerfile.api \
  -t "stocks-in-hand-api:$RELEASE_SHA" backend

docker buildx build --platform linux/amd64 --provenance=false --load \
  -f backend/Dockerfile.scraper \
  -t "stocks-in-hand-scraper:$RELEASE_SHA" backend

docker buildx build --platform linux/amd64 --provenance=false --load \
  -f backend/Dockerfile.analysis \
  -t "stocks-in-hand-analysis:$RELEASE_SHA" backend
```

The scraper contains Chromium. The analysis image contains FinBERT, PDF
rendering, and local OCR models. Do not assume their ECR storage is entirely
free.

```bash
for IMAGE in api scraper analysis; do
  docker tag "stocks-in-hand-${IMAGE}:$RELEASE_SHA" \
    "$ECR_REGISTRY/stocks-in-hand-${IMAGE}:$RELEASE_SHA"
  docker push "$ECR_REGISTRY/stocks-in-hand-${IMAGE}:$RELEASE_SHA"
done
```

## 4. Apply the Supabase migration

Use the direct or session-pooler migration URL, not the Lambda transaction
pooler. Take a backup first. Preview legacy duplicate results:

```sql
SELECT artifact_id, count(*)
FROM artifact_summaries
GROUP BY artifact_id
HAVING count(*) > 1;

SELECT artifact_id, count(*)
FROM artifact_sentiments
GROUP BY artifact_id
HAVING count(*) > 1;

SELECT source_type, url, count(*)
FROM artifacts
WHERE url IS NOT NULL
GROUP BY source_type, url
HAVING count(*) > 1;
```

The migration keeps the newest summary and sentiment for an artifact if legacy
duplicates exist.

```bash
cd backend
read -s "MIGRATION_DATABASE_URL?Supabase migration database URL: "
DATABASE_URL="$MIGRATION_DATABASE_URL" python -m alembic upgrade head
unset MIGRATION_DATABASE_URL
cd ..
```

## 5. Create and review the AWS change set

```bash
sam validate --lint --template-file infra/template.yaml
cfn-lint infra/template.yaml infra/bootstrap.yaml infra/github-oidc.yaml

sam deploy \
  --config-file infra/samconfig.toml \
  --config-env staging \
  --template-file infra/template.yaml \
  --no-execute-changeset \
  --image-repositories "ApiFunction=$ECR_REGISTRY/stocks-in-hand-api" \
  --image-repositories "SchedulerFunction=$ECR_REGISTRY/stocks-in-hand-api" \
  --image-repositories "PublicDiscussionSchedulerFunction=$ECR_REGISTRY/stocks-in-hand-api" \
  --image-repositories "DiscoveryFunction=$ECR_REGISTRY/stocks-in-hand-scraper" \
  --image-repositories "DownloadFunction=$ECR_REGISTRY/stocks-in-hand-scraper" \
  --image-repositories "AnalysisFunction=$ECR_REGISTRY/stocks-in-hand-analysis" \
  --parameter-overrides \
    "Environment=staging" \
    "ParameterPathPrefix=/stocks-in-hand/staging" \
    "OperationsEmail=$OPERATIONS_EMAIL" \
    "ScheduleEnabled=false" \
    "PublicDiscussionScheduleEnabled=false" \
    "AnalysisEnabled=true" \
    "BedrockEnabled=false" \
    "ScheduledTickers=$SCHEDULED_TICKERS" \
    "ScheduledPublicDiscussionSources=$SCHEDULED_PUBLIC_DISCUSSION_SOURCES" \
    "PublicDiscussionPerSourceLimit=$PUBLIC_DISCUSSION_PER_SOURCE_LIMIT" \
    "ApiImageUri=$ECR_REGISTRY/stocks-in-hand-api:$RELEASE_SHA" \
    "ScraperImageUri=$ECR_REGISTRY/stocks-in-hand-scraper:$RELEASE_SHA" \
    "AnalysisImageUri=$ECR_REGISTRY/stocks-in-hand-analysis:$RELEASE_SHA"
```

Person 1 must export and review the CloudFormation change set. Person 2 executes
only the approved ARN. Confirm the SNS alarm subscription email after execution.
CloudFront can take several minutes to finish deploying.

## 6. Build and upload the frontend

```bash
cd frontend
npm ci
npm run build
cd ..

export FRONTEND_BUCKET="$(aws cloudformation describe-stacks \
  --stack-name stocks-in-hand-staging \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendBucketName`].OutputValue' \
  --output text)"

export DISTRIBUTION_ID="$(aws cloudformation describe-stacks \
  --stack-name stocks-in-hand-staging \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendDistributionId`].OutputValue' \
  --output text)"

export FRONTEND_URL="$(aws cloudformation describe-stacks \
  --stack-name stocks-in-hand-staging \
  --query 'Stacks[0].Outputs[?OutputKey==`FrontendUrl`].OutputValue' \
  --output text)"

aws s3 sync frontend/out \
  "s3://$FRONTEND_BUCKET/_releases/$RELEASE_SHA" \
  --cache-control "no-cache"
aws s3 sync frontend/out "s3://$FRONTEND_BUCKET" \
  --delete \
  --exclude "_releases/*" \
  --cache-control "no-cache"
aws s3 sync frontend/out/_next/static \
  "s3://$FRONTEND_BUCKET/_next/static" \
  --cache-control "public,max-age=31536000,immutable"
aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*"

echo "$FRONTEND_URL"
```

The frontend is a static export; no Next.js server is deployed. Browser API
calls use the same CloudFront hostname under `/api/*`.

## 7. Create the first administrator

Open the frontend and sign up one account. In the Supabase SQL editor, promote
only that exact account:

```sql
UPDATE investors
SET role = 'admin'
WHERE lower(email) = lower('your-email@example.com');
```

Confirm that exactly one intended row changed. Public sign-up must not grant
administrator access automatically.

## 8. Test all five sources

Sign in as the administrator. Submit these requests through the CloudFront
hostname, retaining the secure session cookie:

```text
POST /api/scrape/CSL
POST /api/scrape/ANZ
POST /api/scrape/CBA
POST /api/scrape/BHP
POST /api/scrape/WES
```

Use a different `Idempotency-Key` for each new run. Follow each returned run ID
through:

1. `scrape_runs` and `artifacts` in Supabase;
2. Queue A and the discovery logs;
3. Queue B and the download logs;
4. the private raw-document bucket;
5. Queue C and the analysis logs; and
6. the final summary and sentiment rows.

Retry one request with the same idempotency key and verify that it does not
create another logical run. Inject one temporary stage failure and confirm only
that queue retries. Inspect any DLQ message before using the SQS console's
**Start DLQ redrive** action.

Do not enable the schedule until every source passes or has a documented
manual-only exception. BHP remains manual if its AWS live test still times out.

## 9. Enable the schedule

The schedule runs at 9:00 AM each Monday in `Australia/Melbourne`. It creates
one idempotent run per scheduled ticker, and each run queues no more than three
new documents from the last thirty days. Cross-run document identities prevent
the same source document from being analysed again.

Redeploy the same image tags to enable it. If BHP did not pass, set
`SCHEDULED_TICKERS=ANZ,CBA,CSL,WES` first.

```bash
sam deploy \
  --config-file infra/samconfig.toml \
  --config-env staging \
  --template-file infra/template.yaml \
  --image-repositories "ApiFunction=$ECR_REGISTRY/stocks-in-hand-api" \
  --image-repositories "SchedulerFunction=$ECR_REGISTRY/stocks-in-hand-api" \
  --image-repositories "PublicDiscussionSchedulerFunction=$ECR_REGISTRY/stocks-in-hand-api" \
  --image-repositories "DiscoveryFunction=$ECR_REGISTRY/stocks-in-hand-scraper" \
  --image-repositories "DownloadFunction=$ECR_REGISTRY/stocks-in-hand-scraper" \
  --image-repositories "AnalysisFunction=$ECR_REGISTRY/stocks-in-hand-analysis" \
  --parameter-overrides \
    "Environment=staging" \
    "ParameterPathPrefix=/stocks-in-hand/staging" \
    "OperationsEmail=$OPERATIONS_EMAIL" \
    "ScheduleEnabled=true" \
    "PublicDiscussionScheduleEnabled=false" \
    "AnalysisEnabled=true" \
    "BedrockEnabled=false" \
    "ScheduledTickers=$SCHEDULED_TICKERS" \
    "ScheduledPublicDiscussionSources=$SCHEDULED_PUBLIC_DISCUSSION_SOURCES" \
    "PublicDiscussionPerSourceLimit=$PUBLIC_DISCUSSION_PER_SOURCE_LIMIT" \
    "ApiImageUri=$ECR_REGISTRY/stocks-in-hand-api:$RELEASE_SHA" \
    "ScraperImageUri=$ECR_REGISTRY/stocks-in-hand-scraper:$RELEASE_SHA" \
    "AnalysisImageUri=$ECR_REGISTRY/stocks-in-hand-analysis:$RELEASE_SHA"
```

Keep it disabled if the projected monthly cost exceeds US$10.

The public discussion schedule runs at 10:00 AM on weekdays. It defaults to
Bluesky and Mastodon with ten items from each source. Enable it only after the
manual collector canaries pass:

```text
PublicDiscussionScheduleEnabled=true
ScheduledPublicDiscussionSources=bluesky,mastodon
PublicDiscussionPerSourceLimit=10
```

Add `reddit` only after both Reddit SSM parameters exist. Add `blog` only after
the feed allowlist exists. Each EventBridge event has a stable idempotency key,
the Lambda has reserved concurrency one, and at most five blog feeds run.

## 10. Configure GitHub Actions with OIDC

The first database migration remains manual. After the manual deployment
passes, create the OIDC roles:

```bash
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name stocks-in-hand-github-oidc \
  --template-file infra/github-oidc.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    "GitHubRepository=Monash-FIT3170/2026W1-Stocks-In-Hand" \
    "GitHubEnvironment=staging"
```

If the AWS account already has
`token.actions.githubusercontent.com` configured as an IAM provider, deploy
with `CreateOidcProvider=false` and pass its ARN as
`ExistingOidcProviderArn`.

Redeploy this stack before the first enabled Brevo release. Existing GitHub
roles created from older revisions do not have the narrowly scoped permission
to check `/stocks-in-hand/staging/brevo-api-key` metadata.

Read the deployment role:

```bash
aws cloudformation describe-stacks \
  --stack-name stocks-in-hand-github-oidc \
  --query 'Stacks[0].Outputs[?OutputKey==`GitHubDeploymentRoleArn`].OutputValue' \
  --output text
```

In GitHub:

1. create an environment named `staging`;
2. add environment variable `AWS_DEPLOY_ROLE_ARN` with that output;
3. add environment variable `OPERATIONS_EMAIL`;
4. add `ALERT_SENDER_EMAIL` after verifying that sender address in Brevo;
5. keep the active `ProtectMain` ruleset with one approval and last-push approval;
6. restrict the `staging` environment to the `main` branch;
7. remove the environment reviewer after the branch restriction is active; and
8. merge an approved pull request to start **Deploy staging release**.

Automatic releases preserve the current stack values for authentication,
schedules, analysis, notifications, Bedrock, tickers, public sources, and the
per-source limit. Set one of these optional `staging` environment variables to
change a value on the next approved merge:

```text
AUTO_DEPLOY_AUTH_PROVIDER
AUTO_DEPLOY_ENABLE_SCHEDULE
AUTO_DEPLOY_ENABLE_PUBLIC_DISCUSSION_SCHEDULE
AUTO_DEPLOY_ENABLE_ANALYSIS
AUTO_DEPLOY_ENABLE_NOTIFICATIONS
AUTO_DEPLOY_ENABLE_BEDROCK
AUTO_DEPLOY_SCHEDULED_TICKERS
AUTO_DEPLOY_SCHEDULED_PUBLIC_DISCUSSION_SOURCES
AUTO_DEPLOY_PUBLIC_DISCUSSION_PER_SOURCE_LIMIT
```

Leave notifications, schedules, and Bedrock disabled until their smoke tests
pass. A manual run of **Deploy staging release** still creates an unexecuted
change set. **Execute approved staging change set** and **Publish staging
frontend** remain available for reviewed recovery work.

The workflows request short-lived AWS tokens through OIDC. Automatic main
deployments execute only after the same workflow passes backend tests, security
checks, frontend tests, image builds, and SAM lint. A failed API health check
prepares a rollback change set but does not downgrade the database.

## Bedrock limits

The image keeps local FinBERT for sentiment and uses Bedrock only for generated
summaries and evidence categorisation:

- `BedrockEnabled=false` omits Bedrock permission by default;
- the API and analysis Lambdas receive permission only when Bedrock is enabled;
- IAM permits only regional `openai.gpt-oss-120b-1:0`;
- API requests use Standard tier and cost-bearing routes require authentication;
- queued analysis uses Flex tier, concurrency one, and SQS batch size one;
- prompts are capped at 30,000 characters and completions at 1,024 tokens; and
- responses must pass the existing strict JSON schemas before storage.

Use on-demand inference only. Do not create Provisioned Throughput. When the
adapter tests pass, request access to the model in Sydney. Deploy one manual
smoke test with both
schedule flags set to `false`, `AnalysisEnabled=true`, and
`BedrockEnabled=true`.
Run one artifact first. Review its token counts and stored output before a
bounded batch.

For an immediate stop, prevent Queue C from starting another analysis Lambda:

```bash
aws lambda put-function-concurrency \
  --region "$AWS_REGION" \
  --function-name stocks-in-hand-staging-analysis \
  --reserved-concurrent-executions 0
```

This does not cancel a request already in flight and creates CloudFormation
drift. Follow it with a stack deployment using `AnalysisEnabled=false` and
`BedrockEnabled=false`. Restore through the stack after reviewing the queue;
do not redrive analysis messages while Bedrock is disabled.

## Stop scheduled and queued analysis

Redeploy the current images with the schedule, Queue C event source, and
Bedrock permission disabled. An invocation already in flight can finish, but
queued documents remain in Queue C without starting more analysis work.

```bash
sam deploy \
  --config-file infra/samconfig.toml \
  --config-env staging \
  --template-file infra/template.yaml \
  --image-repositories "ApiFunction=$ECR_REGISTRY/stocks-in-hand-api" \
  --image-repositories "SchedulerFunction=$ECR_REGISTRY/stocks-in-hand-api" \
  --image-repositories "PublicDiscussionSchedulerFunction=$ECR_REGISTRY/stocks-in-hand-api" \
  --image-repositories "DiscoveryFunction=$ECR_REGISTRY/stocks-in-hand-scraper" \
  --image-repositories "DownloadFunction=$ECR_REGISTRY/stocks-in-hand-scraper" \
  --image-repositories "AnalysisFunction=$ECR_REGISTRY/stocks-in-hand-analysis" \
  --parameter-overrides \
    "Environment=staging" \
    "ParameterPathPrefix=/stocks-in-hand/staging" \
    "OperationsEmail=$OPERATIONS_EMAIL" \
    "ScheduleEnabled=false" \
    "PublicDiscussionScheduleEnabled=false" \
    "AnalysisEnabled=false" \
    "BedrockEnabled=false" \
    "ScheduledTickers=$SCHEDULED_TICKERS" \
    "ScheduledPublicDiscussionSources=$SCHEDULED_PUBLIC_DISCUSSION_SOURCES" \
    "PublicDiscussionPerSourceLimit=$PUBLIC_DISCUSSION_PER_SOURCE_LIMIT" \
    "ApiImageUri=$ECR_REGISTRY/stocks-in-hand-api:$RELEASE_SHA" \
    "ScraperImageUri=$ECR_REGISTRY/stocks-in-hand-scraper:$RELEASE_SHA" \
    "AnalysisImageUri=$ECR_REGISTRY/stocks-in-hand-analysis:$RELEASE_SHA"
```

## DLQ inspection and redrive

Read the DLQ URL from the application stack outputs. Inspect message bodies and
CloudWatch logs before redriving. Do not edit identifiers or copy document
content into a queue message.

```bash
export DLQ_URL="$(aws cloudformation describe-stacks \
  --stack-name stocks-in-hand-staging \
  --query 'Stacks[0].Outputs[?OutputKey==`AnalysisDeadLetterQueueUrl`].OutputValue' \
  --output text)"

aws sqs receive-message \
  --queue-url "$DLQ_URL" \
  --attribute-names All \
  --message-attribute-names All \
  --max-number-of-messages 1

export DLQ_ARN="$(aws sqs get-queue-attributes \
  --queue-url "$DLQ_URL" \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' \
  --output text)"

aws sqs start-message-move-task --source-arn "$DLQ_ARN"
```

Repeat with the discovery or download DLQ output when that is the failed stage.
Redrive sends the item back to its original source queue and does not rerun
earlier successful stages.

## Rollback

ECR keeps the two newest image versions. Use **Prepare staging backend rollback**
with the previous full SHA. Person 1 reviews that change set before Person 2
executes it. Each Lambda publishes through its `live` alias. Use **Roll back
staging frontend** to restore the matching S3 release snapshot and invalidate
CloudFront. Do not downgrade the database automatically. Use a forward-fix
migration if the schema changed.

Verify after rollback:

```text
GET /api/health
sign in and GET /api/auth/me
GET /api/tickers
```

## Removal

First disable the schedule. The raw/frontend buckets and ECR repositories are
retained deliberately. Confirm their contents are no longer required, empty
the two application buckets, and then delete the application and OIDC stacks.
Delete the bootstrap stack only after the application no longer references its
images. Because ECR repositories use a retain policy, delete them manually only
after confirming rollback images are no longer needed.
