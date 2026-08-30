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
                                |           |
                                v           v
                            Supabase    Queue D: notifications
                                                |
                                                v
                                      Notification Lambda
                                                |
                                                v
                                            Brevo API
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
| Noncurrent frontend versions | 14 days |
| CloudWatch log retention | 7 days |
| ECR images retained per repository | 2 |
| Discovery concurrency | 1 |
| Download concurrency | 2 |
| Analysis concurrency | 1 |
| Notification delivery | Disabled by default |
| Notification concurrency | 1 |
| Alert commitments per 24 hours | 180 |
| Direct alerts per investor and run | 5, then one rollup |

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
/stocks-in-hand/staging/brevo-api-key
/stocks-in-hand/staging/reddit-client-id
/stocks-in-hand/staging/reddit-client-secret
/stocks-in-hand/staging/public-discussion-feed-urls
```

The database URL must be the Supabase transaction-mode pooler URL used by
short-lived Lambda connections. Use a direct or session-pooler connection for
Alembic migrations. Groq and public discussion parameters are optional. Reddit
is disabled without both Reddit parameters. Blog collection is disabled when
the comma-separated feed allowlist parameter is absent.

Only `ANZ`, `BHP`, `CBA`, `CSL`, and `WES` are accepted. The scheduled subset
is configured separately from the set available for manual administrator
requests.

### Brevo watchlist alerts

`NotificationsEnabled` is the deployment master switch and defaults to
`false`. When false, analysis does not publish notification messages, the SQS
event source stays disabled, and the Brevo API key is not loaded. The
notification queue, dead-letter queue, worker, log group, and alarm still exist
for a safe dark launch.

`AlertSenderEmail` is required when `NotificationsEnabled=true`. The address
must be verified in the Brevo account. The staging workflow passes it from the
GitHub `ALERT_SENDER_EMAIL` variable. Store the Brevo API key in the SSM
`SecureString` parameter `/stocks-in-hand/staging/brevo-api-key`. Set the GitHub
variable in the protected `staging` environment before preparing an enabled
change set.

Recipient confirmation is owned by the app. Enabling alerts sends a signed,
24-hour link through Brevo. Clicking it marks that subscription as verified.
Recipients do not need a Brevo account or a Brevo contact record.

The other template controls are `AlertDailyBudget`, which defaults to `180`,
and `AlertMaxPerInvestorPerRun`, which defaults to `5`. The worker sends at
most one rollup after the per-run cap. Budget suppression is terminal and does
not create DLQ traffic.

## Schedule policy

Both EventBridge schedules are created in the disabled state. The announcement
schedule runs at 9:00 AM each Monday. The public discussion schedule runs at
10:00 AM on weekdays. Both use the `Australia/Melbourne` timezone.

Enable only sources that have passed an AWS smoke test. If BHP still times out,
leave BHP available for manual runs but omit it from `ScheduledTickers`.
Public discussion collection defaults to Bluesky and Mastodon, ten items each,
with one concurrent scheduler invocation. Reddit and blogs require their SSM
settings before they are included.

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
- Notification delivery uses a database claim before Brevo. Duplicate queue
  messages do not send a second email, and stale claims can be recovered.
- Unsubscribe tokens are stored as hashes. The public endpoint returns the same
  response for valid and invalid tokens.
- Primary queues retain messages for four days, DLQs retain them for fourteen
  days, and messages move to a DLQ after five receives.
- Discovery and download queues use 30-minute visibility timeouts. Analysis
  uses 72 minutes, which is six times its 12-minute Lambda timeout.
- IAM permissions are scoped by worker role, queue, bucket prefix, and SSM
  parameter path.

## Deployment sequence

1. Run backend tests, frontend static export, static checks, image smoke tests,
   SAM validation, and CloudFormation linting. The compose suite includes
   Brevo dry-run and notification alert contracts.
2. Back up Supabase, preview legacy duplicate analysis rows, and apply the
   Alembic migration using the migration connection.
3. Deploy `infra/bootstrap.yaml` to create the budget and ECR repositories.
4. Store the runtime SSM parameters interactively.
5. Build and push immutable API, scraper, and analysis images tagged with the
   full Git commit SHA.
6. Verify the sender in Brevo, store the Brevo API key in SSM, set the protected
   GitHub `ALERT_SENDER_EMAIL` variable, and leave `enable_notifications=false`.
7. Create the SAM change set with both schedule flags set to `false` and
   notifications disabled. Person 1 reviews it before Person 2 executes the
   approved ARN.
8. Upload a SHA-named `frontend/out` snapshot, publish it to the versioned
   frontend bucket, and invalidate CloudFront.
9. Create exactly one administrator and manually trigger one bounded run for
   every enabled source. Public discussion collector routes require that
   administrator session.
10. Verify the database, queues, private S3 object, analysis result, logs,
    duplicate suppression, and one DLQ redrive.
11. Enable alerts through a second reviewed change set, then complete the Brevo
    smoke test below.
12. Enable either schedule only after its sources pass bounded smoke tests.
13. Configure the manual GitHub OIDC workflow only after the first manual
     deployment succeeds.

Every Lambda publishes through its `live` alias. Backend rollback creates a new
reviewed change set that points to the previous retained ECR image SHA. Database
migrations are never downgraded automatically.

Exact commands, rollback steps, DLQ procedures, and teardown instructions are
in `infra/README.md`.

## Brevo alert rollout and rollback

Keep alerts disabled during the first deployment. Confirm the stack contains
`NotificationQueue`, `NotificationFunction`, the notification DLQ alarm, and
the new alert tables. The notification SQS event source must remain disabled.

Before enabling alerts:

1. Confirm the sender address is verified in the Brevo account.
2. Confirm `/stocks-in-hand/staging/brevo-api-key` exists as an SSM
   `SecureString`.
3. Confirm `ALERT_SENDER_EMAIL` is set in the GitHub `staging` environment.
4. Use one staging investor whose account email you control.
5. Prepare a new release with `enable_notifications=true` and review its change
   set. `AlertSenderEmail` cannot be empty in this change set.
6. Execute the approved change set, then enable alerts in the investor's
   notification settings.
7. Click the app confirmation link from the Brevo email. Confirm the UI reports
   that the address is verified.
8. Trigger one bounded scrape and confirm exactly one email and one `sent`
   delivery ledger row.
9. Replay the same notification message and confirm no second email is sent.
10. Click unsubscribe and confirm the subscription is disabled.

Use an inbox you control for the real smoke test. Dry-run and unit tests do not
prove Brevo delivery, confirmation email receipt, or inbox rendering.

To stop alert delivery, prepare and execute a reviewed change set with
`enable_notifications=false`. This stops the producer, skips Brevo secret
loading, and disables the notification event source. Messages already in Queue
D remain for up to four days. Inspect that queue before re-enabling alerts,
since retained messages may run later. Do not purge or redrive it without an
approved incident decision.

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
- A verified, opted-in investor receives one matching Brevo alert. Replays do
  not send another email, and the unsubscribe link disables future delivery.
- Buckets are private, the weekly schedule is disabled by default, retention
  policies are active, and projected AWS usage remains below US$10 per month.

## Known release gate

BHP previously timed out during local live validation. It must pass in AWS
before being placed on the weekly schedule. A documented source-specific
exception is acceptable for the demo as long as the other sources pass and
BHP remains manual.

Brevo remains a separate release gate. Dry-run cannot prove recipient
confirmation or real inbox delivery. Do not enable notifications for general
staging users until the verified-address smoke test passes.
