# Staging deployment

This guide creates one staging deployment in `ap-southeast-2`. Start manually,
leave the EventBridge schedule disabled, and configure GitHub Actions only after
ANZ, CBA, BHP, WES, and CSL work end to end.

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
export SCHEDULED_TICKERS=ANZ,BHP,CBA,CSL,WES
export RELEASE_TAG="$(git rev-parse --short=12 HEAD)"
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
  --no-fail-on-empty-changeset
```

Open AWS Billing and Cost Management and verify that
`stocks-in-hand-monthly-cost` exists before running the pipeline.

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

Groq summaries are optional:

```bash
read -s "GROQ_API_KEY?Groq API key: "
aws ssm put-parameter \
  --region "$AWS_REGION" \
  --name /stocks-in-hand/staging/groq-api-key \
  --type SecureString \
  --value "$GROQ_API_KEY" \
  --overwrite
unset GROQ_API_KEY
```

If the Groq parameter is absent, extraction, classification, OCR, and FinBERT
still run.

## 3. Build and push the Lambda images

```bash
aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker buildx build --platform linux/amd64 --provenance=false --load \
  -f backend/Dockerfile.api \
  -t "stocks-in-hand-api:$RELEASE_TAG" backend

docker buildx build --platform linux/amd64 --provenance=false --load \
  -f backend/Dockerfile.scraper \
  -t "stocks-in-hand-scraper:$RELEASE_TAG" backend

docker buildx build --platform linux/amd64 --provenance=false --load \
  -f backend/Dockerfile.analysis \
  -t "stocks-in-hand-analysis:$RELEASE_TAG" backend
```

The scraper contains Chromium. The analysis image contains FinBERT, PDF
rendering, and local OCR models. Do not assume their ECR storage is entirely
free.

```bash
for IMAGE in api scraper analysis; do
  docker tag "stocks-in-hand-${IMAGE}:$RELEASE_TAG" \
    "$ECR_REGISTRY/stocks-in-hand-${IMAGE}:$RELEASE_TAG"
  docker push "$ECR_REGISTRY/stocks-in-hand-${IMAGE}:$RELEASE_TAG"
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

## 5. Deploy AWS with the schedule off

```bash
sam validate --lint --template-file infra/template.yaml
cfn-lint infra/template.yaml infra/bootstrap.yaml infra/github-oidc.yaml

sam deploy --guided \
  --config-file infra/samconfig.toml \
  --config-env staging \
  --template-file infra/template.yaml \
  --parameter-overrides \
    "Environment=staging" \
    "ParameterPathPrefix=/stocks-in-hand/staging" \
    "OperationsEmail=$OPERATIONS_EMAIL" \
    "ScheduleEnabled=false" \
    "ScheduledTickers=$SCHEDULED_TICKERS" \
    "ApiImageUri=$ECR_REGISTRY/stocks-in-hand-api:$RELEASE_TAG" \
    "ScraperImageUri=$ECR_REGISTRY/stocks-in-hand-scraper:$RELEASE_TAG" \
    "AnalysisImageUri=$ECR_REGISTRY/stocks-in-hand-analysis:$RELEASE_TAG"
```

Review the CloudFormation change set before approving it. Confirm the SNS alarm
subscription email. CloudFront can take several minutes to finish deploying.

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

aws s3 sync frontend/out "s3://$FRONTEND_BUCKET" --delete
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
  --parameter-overrides \
    "Environment=staging" \
    "ParameterPathPrefix=/stocks-in-hand/staging" \
    "OperationsEmail=$OPERATIONS_EMAIL" \
    "ScheduleEnabled=true" \
    "ScheduledTickers=$SCHEDULED_TICKERS" \
    "ApiImageUri=$ECR_REGISTRY/stocks-in-hand-api:$RELEASE_TAG" \
    "ScraperImageUri=$ECR_REGISTRY/stocks-in-hand-scraper:$RELEASE_TAG" \
    "AnalysisImageUri=$ECR_REGISTRY/stocks-in-hand-analysis:$RELEASE_TAG"
```

Keep it disabled if the projected monthly cost exceeds US$10.

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
3. add environment variable `OPERATIONS_EMAIL`; and
4. manually run **Deploy staging** from the Actions page;
5. leave `enable_schedule` set to `false` for ordinary deployments; and
6. set `scheduled_tickers` only to sources that passed their AWS smoke test.

The workflow requests a short-lived AWS token through OIDC, builds immutable
images, deploys the SAM stack, uploads the static frontend, and invalidates
CloudFront. It is deliberately `workflow_dispatch` only.

## Disable the schedule immediately

Redeploy the current images with `ScheduleEnabled=false`. This is the primary
cost kill switch and does not interrupt already queued documents.

```bash
sam deploy \
  --config-file infra/samconfig.toml \
  --config-env staging \
  --template-file infra/template.yaml \
  --parameter-overrides \
    "Environment=staging" \
    "ParameterPathPrefix=/stocks-in-hand/staging" \
    "OperationsEmail=$OPERATIONS_EMAIL" \
    "ScheduleEnabled=false" \
    "ScheduledTickers=$SCHEDULED_TICKERS" \
    "ApiImageUri=$ECR_REGISTRY/stocks-in-hand-api:$RELEASE_TAG" \
    "ScraperImageUri=$ECR_REGISTRY/stocks-in-hand-scraper:$RELEASE_TAG" \
    "AnalysisImageUri=$ECR_REGISTRY/stocks-in-hand-analysis:$RELEASE_TAG"
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

ECR keeps the two newest image versions. To roll back the backend, set
`RELEASE_TAG` to the previous known-good immutable tag and redeploy the SAM
stack with `ScheduleEnabled=false`. Reapply the previous tested `frontend/out`
artifact and invalidate CloudFront. Do not automatically downgrade the
database. Use a forward-fix migration if the schema changed.

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
