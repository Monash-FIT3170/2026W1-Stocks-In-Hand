# Low-cost AWS deployment

## Goal

Deploy one public staging/demo environment in `ap-southeast-2` while keeping
the AWS budget below US$10 per month. Supabase remains the application
database and is outside the AWS budget.

This is deliberately a small deployment. It does not create RDS, EC2, ECS,
a VPC, a NAT Gateway, WAF, a custom domain, or a second production stack.

## Architecture

```text
Browser
  |
  v
CloudFront
  | default                         | /api/*
  v                                 v
Private frontend S3             API Gateway HTTP API
                                      |
                                      v
                                  FastAPI Lambda
                                      |
                                      v
                              Queue A: discovery
                                      |
                                      v
                              Discovery Lambda
                                      |
                                      v
                              Queue B: download
                                      |
                                      v
                               Download Lambda
                                      |
                                      v
                         Private raw-document S3
                                      |
                              S3 ObjectCreated
                                      |
                                      v
                              Queue C: analysis
                                      |
                                      v
                               Analysis Lambda
                                      |
                                      v
                                  Supabase
```

Each primary queue has its own dead-letter queue. Discovery, downloading, and
analysis therefore retry independently. The downloader does not send Queue C
messages directly. Native S3 notifications remove the failure window between
storing a document and publishing its analysis task.

## Cost controls

The deployment starts with these fixed limits:

| Control | Initial value |
|---|---:|
| AWS monthly budget | US$10 |
| Amazon Bedrock monthly budget | US$1 |
| Amazon Bedrock access | Disabled |
| Amazon Bedrock model | Nova Micro only |
| Bedrock input per request | 2,000 tokens |
| Bedrock output per request | 64 tokens |
| Discovery lookback | 30 days |
| New documents per ticker and run | 3 |
| Document size | 10 MiB |
| PDF pages | 100 |
| OCR pages | 5 |
| Sentiment input | 50,000 characters |
| Raw-document retention | 30 days |
| CloudWatch log retention | 7 days |
| ECR images retained per repository | 2 |
| Discovery concurrency | 1 |
| Download concurrency | 2 |
| Analysis concurrency | 1 |

Documents receive a stable, database-unique identity derived from their source
adapter and source identifier or canonical URL. A later run skips a document
that has already entered the pipeline, so weekly runs do not repeatedly pay to
analyse the same announcement.

The account-wide AWS Budget sends email at 50 percent actual spend, 80 percent
forecast spend, and 100 percent actual spend. A separate Bedrock budget sends
actual-spend emails at 10, 50, and 100 percent of US$1. Both budgets exclude
credits and refunds so usage is visible before promotional credits run out.
These notifications are not a hard spending cap and billing data can be
delayed. The only zero-charge Bedrock setting is `BedrockEnabled=false`, which
omits model invocation permission from the analysis Lambda. The immediate cost
controls are the disabled schedule, bounded document counts, short retention,
API throttling, and Lambda reserved concurrency.

Bedrock is restricted to on-demand `amazon.nova-micro-v1:0` in Sydney. No
Provisioned Throughput is created. `AnalysisEnabled=false` stops Queue C from
starting new work, while `BedrockEnabled=false` removes Bedrock permission. The
2,000 input-token and 64 output-token values are ready for the Bedrock adapter;
the current release still uses local FinBERT and does not make Bedrock calls.

The deployment intentionally avoids paid-by-default features such as
provisioned concurrency, X-Ray, detailed API metrics, customer-managed KMS
keys, Secrets Manager, dashboards, WAF, and NAT Gateway.

## Runtime configuration

Runtime secrets are standard SSM `SecureString` parameters encrypted with the
AWS-managed SSM key:

```text
/stocks-in-hand/staging/database-url
/stocks-in-hand/staging/groq-api-key
```

The database URL must be the Supabase transaction-mode pooler URL used by
short-lived Lambda connections. Use a direct or session-pooler connection for
Alembic migrations. Groq is optional; FinBERT, extraction, and OCR continue
without it.

Only `ANZ`, `BHP`, `CBA`, `CSL`, and `WES` are accepted. The scheduled subset
is configured separately from the set available for manual administrator
requests.

## Schedule policy

The EventBridge Scheduler resource is created in the disabled state. After
manual validation it can run at 9:00 AM each Monday using the
`Australia/Melbourne` timezone.

Enable only sources that have passed an AWS smoke test. If BHP still times out,
leave BHP available for manual runs but omit it from `ScheduledTickers`.

## Security and reliability

- Both S3 buckets block public access and require TLS.
- CloudFront reads the frontend bucket through Origin Access Control.
- Raw documents use SSE-S3 and immutable, checksum-addressed keys.
- Download URLs are HTTPS allowlisted and checked against private address
  resolution, unsafe redirects, MIME mismatches, invalid signatures, and size
  limits.
- Queue messages contain identifiers and metadata, not document bodies,
  extracted text, cookies, or secrets.
- Each stage validates its message and treats SQS and S3 delivery as
  at-least-once.
- Database uniqueness, conditional S3 writes, and monotonic status transitions
  make retries idempotent.
- Primary queues retain messages for four days, DLQs retain them for fourteen
  days, and messages move to a DLQ after five receives.
- Discovery and download queues use 30-minute visibility timeouts. Analysis
  uses 72 minutes, which is six times its 12-minute Lambda timeout.
- IAM permissions are scoped by worker role, queue, bucket prefix, and SSM
  parameter path.

## Deployment sequence

1. Run backend tests, frontend static export, static checks, image smoke tests,
   SAM validation, and CloudFormation linting.
2. Back up Supabase, preview legacy duplicate analysis rows, and apply the
   Alembic migration using the migration connection.
3. Deploy `infra/bootstrap.yaml` to create the budget and ECR repositories.
4. Store the runtime SSM parameters interactively.
5. Build and push immutable API, scraper, and analysis images tagged with the
   Git commit.
6. Deploy `infra/template.yaml` with `ScheduleEnabled=false`.
7. Upload `frontend/out` to the frontend bucket and invalidate CloudFront.
8. Create exactly one administrator and manually trigger one bounded run for
   every source.
9. Verify the database, queues, private S3 object, analysis result, logs,
   duplicate suppression, and one DLQ redrive.
10. Enable the weekly schedule only for sources that pass.
11. Configure the manual GitHub OIDC workflow only after the first manual
    deployment succeeds.

Exact commands, rollback steps, DLQ procedures, and teardown instructions are
in `infra/README.md`.

## Acceptance criteria

- The frontend and its generated ticker routes load through CloudFront,
  including direct refreshes.
- `/api/health`, authentication cookies, scrape creation, and scrape-run status
  work through the CloudFront hostname.
- An administrator scrape returns HTTP 202 with `status`, `ticker`, and
  `scrape_run_id`, and repeated `Idempotency-Key` values return the same run.
- Every successful source flows through Queue A, Queue B, raw S3, Queue C, and
  Supabase.
- Failure in one stage retries only that stage and eventually reaches its own
  DLQ.
- Duplicate API, SQS, S3, and cross-run document deliveries do not create
  duplicate analysis results.
- Buckets are private, the weekly schedule is disabled by default, retention
  policies are active, and projected AWS usage remains below US$10 per month.

## Known release gate

BHP previously timed out during local live validation. It must pass in AWS
before being placed on the weekly schedule. A documented source-specific
exception is acceptable for the demo as long as the other sources pass and
BHP remains manual.
