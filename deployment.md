```markdown
# AWS Scraping and Document Analysis Architecture Plan

## 1. Objective

Build an event-driven AWS pipeline that:

1. Accepts websites to be scraped.
2. Discovers downloadable documents.
3. Downloads and stores each document.
4. Analyses each document independently.
5. Saves the analysis results to the application database.
6. Automatically retries failed processing without repeating completed stages.

The core architectural principle is to separate document discovery, downloading and analysis into independent services connected through Amazon SQS.

---

## 2. High-Level Architecture

```text
User or Scheduled Job
        ↓
Backend API
        ↓
Website Queue
        ↓
Document Discovery Lambda
        ↓
Document Download Queue
        ↓
Document Download Lambda
        ↓
Raw Documents S3 Bucket
        ↓
Document Analysis Queue
        ↓
Document Analysis Lambda
        ↓
Application Database
```

Supporting AWS services:

```text
Amazon EventBridge     → Scheduled scraping jobs
Amazon CloudWatch      → Logging, monitoring and alerts
AWS IAM                → Service permissions
AWS Secrets Manager    → Credentials and API keys
Dead-letter queues     → Failed-message handling
```

---

## 3. Frontend Architecture

```text
User
  ↓
Amazon CloudFront
  ↓
Frontend S3 Bucket
```

### Amazon S3 Frontend Bucket

The frontend S3 bucket stores the compiled frontend application, including:

- HTML files
- CSS files
- JavaScript files
- Images
- Static assets

The frontend bucket should:

- Be private.
- Allow access through CloudFront only.
- Use encryption at rest.
- Enable versioning where appropriate.
- Block all direct public access.

### Amazon CloudFront

CloudFront distributes the frontend application to users.

It provides:

- HTTPS support.
- Content caching.
- Faster global content delivery.
- Protection of the underlying S3 bucket.
- Optional integration with AWS Web Application Firewall.

---

## 4. Backend API Architecture

```text
Frontend
   ↓
Amazon API Gateway
   ↓
Backend Lambda
   ↓
Supabase
```

### Amazon API Gateway

API Gateway exposes the backend API used by the frontend.

Example endpoints may include:

```text
POST /scraping-jobs
GET /scraping-jobs
GET /scraping-jobs/{jobId}
GET /documents
GET /documents/{documentId}
GET /analysis-results
POST /scraping-jobs/{jobId}/retry
```

API Gateway should manage:

- Request routing.
- Authentication.
- Request validation.
- Rate limiting.
- Cross-origin resource sharing.
- API access logging.

### Backend Lambda

The backend Lambda manages application-level operations.

Its responsibilities may include:

- Creating scraping jobs.
- Validating submitted websites.
- Recording jobs in the database.
- Placing website messages into the website queue.
- Retrieving job statuses.
- Returning document and analysis data.
- Supporting manual retries.
- Managing user permissions.

The backend Lambda should not directly perform scraping, document downloading or document analysis.

---

## 5. Scraping Pipeline

## Stage 1: Website Submission

A scraping job may begin from:

- A website submitted by a user.
- A scheduled EventBridge rule.
- A manually retried job.
- An internal application workflow.

The backend should first create a scraping job record in the database.

Example initial status:

```text
QUEUED
```

The backend then places a message into the website queue.

Example message:

```json
{
  "jobId": "job-123",
  "websiteId": "website-456",
  "url": "https://example.com/reports",
  "requestedAt": "2026-07-28T09:00:00Z"
}
```

---

## Stage 2: Website Queue

### Amazon SQS Website Queue

The website queue stores websites waiting to be scanned.

Its purpose is to separate the backend API from the scraping workload.

Benefits include:

- Reliable message delivery.
- Automatic retry behaviour.
- Independent scaling.
- Protection from traffic spikes.
- Failure isolation.

The website queue triggers the Document Discovery Lambda.

A dead-letter queue should be attached to the website queue.

---

## Stage 3: Document Discovery Lambda

The Document Discovery Lambda reads website jobs from the website queue.

Its responsibilities are to:

1. Validate the submitted website URL.
2. Visit the website.
3. Locate downloadable documents.
4. Extract document links.
5. Convert relative links into complete URLs.
6. Remove duplicate links.
7. Validate supported document types.
8. Create document records in the database.
9. Place each document link into the document download queue.
10. Update the website job status.

Example supported document types may include:

```text
PDF
DOCX
XLSX
CSV
TXT
HTML
```

Example message placed into the document download queue:

```json
{
  "jobId": "job-123",
  "documentId": "document-789",
  "sourceWebsite": "https://example.com/reports",
  "documentUrl": "https://example.com/reports/report.pdf"
}
```

The discovery Lambda should only discover documents.

It should not download or analyse them.

---

## Stage 4: Document Download Queue

### Amazon SQS Document Download Queue

The document download queue contains individual documents that need to be downloaded.

Each message should represent one document.

This means that if one document fails:

- Only that document is retried.
- Other documents can continue processing.
- The website does not need to be scanned again.

For example, if a website contains 100 documents and one download fails, the other 99 documents can still complete successfully.

A dead-letter queue should be attached to the document download queue.

---

## Stage 5: Document Download Lambda

The Document Download Lambda reads document messages from the document download queue.

Its responsibilities are to:

1. Validate the document URL.
2. Request the document.
3. Confirm that the response contains a supported file.
4. Enforce maximum file-size limits.
5. Calculate a checksum.
6. Detect duplicate documents.
7. Save the original document in Amazon S3.
8. Update the document record in the database.
9. Place the S3 location into the document analysis queue.

Example S3 object key:

```text
raw-documents/{jobId}/{documentId}/original.pdf
```

Example message placed into the document analysis queue:

```json
{
  "jobId": "job-123",
  "documentId": "document-789",
  "bucket": "application-raw-documents",
  "objectKey": "raw-documents/job-123/document-789/original.pdf"
}
```

The downloader should not perform sentiment analysis or content extraction.

---

## 6. Document Storage

### Amazon S3 Raw Documents Bucket

Use a separate S3 bucket for documents collected by the scraping pipeline.

This bucket should be separate from the frontend S3 bucket.

Example bucket separation:

```text
Frontend bucket:
application-frontend-production

Raw documents bucket:
application-raw-documents-production
```

The raw documents bucket should contain the original downloaded files.

The database should store references to the S3 objects rather than storing large files directly.

Example database reference:

```text
s3://application-raw-documents-production/raw-documents/job-123/document-789/original.pdf
```

### Recommended S3 Configuration

The raw documents bucket should use:

- Block Public Access.
- Server-side encryption.
- Object versioning where required.
- Lifecycle rules.
- Consistent object naming.
- Restricted IAM access.
- Access logging where appropriate.

Lifecycle policies may be used to:

- Move older documents to cheaper storage.
- Delete temporary processing files.
- Retain original documents for a defined period.
- Permanently retain documents required for auditing.

---

## 7. Document Analysis Pipeline

## Stage 6: Document Analysis Queue

### Amazon SQS Document Analysis Queue

The document analysis queue contains references to documents that have already been stored in S3.

This ensures that analysis can be retried without downloading the document again.

The document analysis queue triggers the Document Analysis Lambda.

A dead-letter queue should be attached to the document analysis queue.

---

## Stage 7: Document Analysis Lambda

The Document Analysis Lambda reads a document location from the document analysis queue.

Its responsibilities are to:

1. Retrieve the document from S3.
2. Identify the document format.
3. Extract readable text.
4. Clean and normalise the extracted content.
5. Split large documents into manageable sections.
6. Perform sentiment analysis.
7. Perform any additional required analysis.
8. Combine section-level results.
9. Store the final results in the database.
10. Update the document and job statuses.

Possible analysis outputs include:

- Overall sentiment.
- Sentiment score.
- Positive, neutral or negative classification.
- Document summary.
- Named entities.
- Key topics.
- Keywords.
- Risks or concerns.
- Important quotations.
- Document date.
- Organisation names.
- Confidence scores.

The analysis Lambda should operate only on documents already stored in S3.

---

## 8. Large Document Handling

AWS Lambda has execution time, memory and temporary storage limits.

For large documents, the analysis process may need to be divided into smaller stages.

Example extended analysis architecture:

```text
Document Analysis Queue
        ↓
Text Extraction Lambda
        ↓
Extracted Text S3
        ↓
Analysis Chunk Queue
        ↓
Chunk Analysis Lambda
        ↓
Result Aggregation Lambda
        ↓
Application Database
```

This additional separation may be introduced when:

- Documents regularly exceed Lambda execution limits.
- Analysis requires many external API calls.
- Documents contain hundreds of pages.
- OCR is required.
- Analysis requires substantial computing resources.

For smaller documents, a single Document Analysis Lambda may be sufficient.

---

## 9. Database Structure

Supabase may remain the application database.

The database should store metadata, processing state and analysis results rather than the full downloaded files.

### Scraping Jobs Table

Example fields:

```text
id
user_id
source_website
status
documents_discovered
documents_downloaded
documents_analysed
documents_failed
created_at
started_at
completed_at
last_error
```

### Websites Table

Example fields:

```text
id
url
domain
display_name
last_scraped_at
next_scrape_at
is_active
created_at
```

### Documents Table

Example fields:

```text
id
job_id
website_id
source_url
file_name
file_type
file_size
checksum
s3_bucket
s3_object_key
download_status
analysis_status
downloaded_at
analysed_at
last_error
created_at
```

### Analysis Results Table

Example fields:

```text
id
document_id
sentiment_label
sentiment_score
summary
keywords
topics
entities
analysis_model
analysis_version
confidence_score
created_at
```

### Processing Attempts Table

Example fields:

```text
id
job_id
document_id
processing_stage
attempt_number
status
error_message
started_at
completed_at
```

This structure makes it possible to trace every website, document and processing attempt.

---

## 10. Status Tracking

Each scraping job should have a clear status.

Example job statuses:

```text
CREATED
QUEUED
DISCOVERING
DOWNLOADING
ANALYSING
PARTIALLY_COMPLETED
COMPLETED
FAILED
```

Each document should also have its own status.

Example document statuses:

```text
DISCOVERED
QUEUED_FOR_DOWNLOAD
DOWNLOADING
DOWNLOADED
QUEUED_FOR_ANALYSIS
ANALYSING
COMPLETED
DOWNLOAD_FAILED
ANALYSIS_FAILED
```

A scraping job may be marked as partially completed when some documents succeed and others fail.

---

## 11. Retry Behaviour

Each pipeline stage must be independently retryable.

### Discovery Failure

```text
Website Queue
    ↓
Discovery Lambda fails
    ↓
Website message becomes visible again
    ↓
Discovery is retried
```

### Download Failure

```text
Document Download Queue
    ↓
One document download fails
    ↓
Only that document is retried
```

### Analysis Failure

```text
Document Analysis Queue
    ↓
Analysis fails
    ↓
Document remains stored in S3
    ↓
Only analysis is retried
```

Completed stages should not need to be repeated.

---

## 12. Dead-Letter Queues

Each primary queue should have its own dead-letter queue.

```text
Website Queue
    └── Website Dead-Letter Queue

Document Download Queue
    └── Download Dead-Letter Queue

Document Analysis Queue
    └── Analysis Dead-Letter Queue
```

Messages should move to a dead-letter queue after a configured number of failed attempts.

The system should support:

- Viewing failed messages.
- Recording failure reasons.
- Correcting the underlying issue.
- Replaying failed messages.
- Alerting administrators.

---

## 13. Idempotency and Duplicate Protection

Amazon SQS may deliver a message more than once.

Each processing stage must therefore be idempotent.

Idempotent processing means that processing the same message multiple times should not create duplicate data or unnecessarily repeat completed work.

### Discovery Idempotency

Before creating a document record, check whether the same document URL has already been recorded for the job.

### Download Idempotency

Before downloading, check whether the document has already been successfully stored.

A checksum can also detect duplicate content downloaded from different URLs.

### Analysis Idempotency

Before running analysis, check whether a completed result already exists for the same:

```text
Document ID
Analysis type
Analysis model
Analysis version
```

An idempotency key may be based on:

```text
jobId + documentId + processingStage
```

---

## 14. SQS Configuration

Each queue should be configured with:

- A visibility timeout longer than the Lambda processing timeout.
- A dead-letter queue.
- A retry limit.
- Message retention settings.
- Encryption.
- An appropriate batch size.
- Partial batch failure support.

For example, if a Lambda can run for five minutes, the queue visibility timeout should be longer than five minutes.

This prevents the same message from being processed by multiple Lambda invocations while the first invocation is still running.

---

## 15. Lambda Configuration

Each Lambda should have settings appropriate to its workload.

### Document Discovery Lambda

Likely characteristics:

- Lower concurrency.
- Short-to-medium timeout.
- Website rate limiting.
- Network request controls.
- Maximum page and link limits.

### Document Download Lambda

Likely characteristics:

- Moderate concurrency.
- Increased temporary storage where required.
- File-size limits.
- Streaming downloads directly to S3 where practical.
- Network timeouts.

### Document Analysis Lambda

Likely characteristics:

- Higher memory allocation.
- Longer timeout.
- Restricted concurrency.
- Access to external analysis APIs or models.
- Higher cost per invocation.

Concurrency limits should prevent the system from overwhelming:

- Source websites.
- Supabase.
- External analysis services.
- API rate limits.
- AWS account limits.

---

## 16. EventBridge Scheduling

Amazon EventBridge can start recurring scraping jobs.

Example:

```text
EventBridge Schedule
        ↓
Job Creation Lambda
        ↓
Website Queue
```

Possible schedules include:

- Daily.
- Weekly.
- Monthly.
- At a specified time.
- Different schedules for different websites.

Scheduled jobs should use the same pipeline as manually submitted jobs.

This avoids maintaining separate scraping logic.

---

## 17. Monitoring and Logging

### Amazon CloudWatch Logs

Each Lambda should log:

- Job ID.
- Document ID.
- Processing stage.
- Attempt number.
- Start time.
- Completion time.
- Processing duration.
- Error type.
- Error message.

Example log entry:

```json
{
  "jobId": "job-123",
  "documentId": "document-789",
  "stage": "DOCUMENT_DOWNLOAD",
  "status": "FAILED",
  "attempt": 2,
  "error": "Request timed out"
}
```

### CloudWatch Metrics

Monitor:

- Queue depth.
- Age of the oldest message.
- Lambda errors.
- Lambda duration.
- Lambda throttling.
- Concurrent executions.
- Dead-letter queue messages.
- Documents processed.
- Failed downloads.
- Failed analyses.
- Average processing time.

### CloudWatch Alerts

Create alerts for:

- Messages entering a dead-letter queue.
- Queues growing unexpectedly.
- Messages remaining unprocessed for too long.
- Increased Lambda error rates.
- Lambda throttling.
- Database connection failures.
- External analysis API failures.

---

## 18. Security

### URL Validation

The system should validate every submitted URL.

It should block requests to:

- Localhost.
- Private network addresses.
- AWS metadata endpoints.
- Internal services.
- Unsupported protocols.
- Redirects to restricted destinations.

This reduces server-side request forgery risks.

### File Validation

The downloader should:

- Restrict supported file types.
- Check the actual content type.
- Enforce file-size limits.
- Reject executable files.
- Avoid executing macros.
- Treat all downloaded files as untrusted.
- Avoid running or opening downloaded content as executable code.

### Encryption

Use encryption:

```text
In transit: HTTPS and TLS
At rest: S3 encryption, SQS encryption and database encryption
```

### S3 Security

Raw documents should:

- Remain private.
- Be accessible only to authorised services.
- Use temporary signed URLs when users need access.
- Never be exposed through a public bucket.

---

## 19. IAM Permissions

Each Lambda should receive only the permissions required for its role.

### Backend Lambda

May require:

- Write access to the website queue.
- Database access.
- Secrets Manager access.

### Document Discovery Lambda

May require:

- Read and delete access for the website queue.
- Write access to the document download queue.
- Database access.

### Document Download Lambda

May require:

- Read and delete access for the document download queue.
- Write access to the raw documents S3 bucket.
- Write access to the document analysis queue.
- Database access.

### Document Analysis Lambda

May require:

- Read and delete access for the document analysis queue.
- Read access to the raw documents S3 bucket.
- Database access.
- Access to analysis API credentials.

No Lambda should receive broad administrator permissions.

---

## 20. Secrets Management

Sensitive values should be stored in:

- AWS Secrets Manager, or
- AWS Systems Manager Parameter Store.

Examples include:

- Supabase credentials.
- API keys.
- Authentication secrets.
- External analysis service keys.
- Signing keys.

Secrets should not be stored in:

- Source code.
- Git repositories.
- Plain-text environment files committed to Git.
- Queue messages.
- CloudWatch logs.

---

## 21. Error Handling

Errors should be divided into retryable and non-retryable errors.

### Retryable Errors

Examples include:

- Website timeout.
- Temporary server error.
- Database connection timeout.
- Analysis API rate limit.
- Temporary AWS service failure.

These errors should allow the message to return to the queue for another attempt.

### Non-Retryable Errors

Examples include:

- Invalid URL.
- Unsupported file format.
- File exceeding the maximum permitted size.
- Permanent HTTP 404 response.
- Blocked internal network address.
- Corrupted document.

These errors should be recorded in the database and should not be retried indefinitely.

---

## 22. Rate Limiting and Website Protection

The scraper should avoid overwhelming external websites.

Controls should include:

- Low discovery concurrency.
- Domain-level request limits.
- Delays between requests where required.
- Maximum pages scanned per website.
- Maximum documents discovered per job.
- Request timeouts.
- Respect for authorised access conditions and website terms.

Download concurrency may be configured separately from discovery concurrency.

---

## 23. Infrastructure Environments

Use separate environments:

```text
Development
Testing or Staging
Production
```

Each environment should have separate:

- SQS queues.
- Dead-letter queues.
- Lambda functions.
- S3 buckets.
- Database configuration.
- Secrets.
- CloudWatch alerts.

Example naming:

```text
scraping-website-queue-dev
scraping-website-queue-staging
scraping-website-queue-prod
```

---

## 24. Infrastructure as Code

The AWS infrastructure should be defined using Infrastructure as Code.

Suitable options include:

- AWS Cloud Development Kit.
- Terraform.
- AWS CloudFormation.
- AWS Serverless Application Model.

Infrastructure as Code should define:

- SQS queues.
- Dead-letter queues.
- Lambda functions.
- Lambda event-source mappings.
- S3 buckets.
- IAM roles and policies.
- EventBridge rules.
- CloudWatch alarms.
- Secrets references.
- API Gateway configuration.

This makes deployment repeatable and reduces configuration drift.

---

## 25. Recommended Final Architecture

```text
                                  AWS Cloud
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  Frontend                                                               │
│                                                                         │
│  User → CloudFront → Frontend S3 Bucket                                 │
│                                                                         │
│  Backend                                                                │
│                                                                         │
│  User → API Gateway → Backend Lambda → Supabase                         │
│                           │                                             │
│                           ↓                                             │
│  Scraping Pipeline                                                      │
│                                                                         │
│  EventBridge ──────────→ Website SQS Queue                              │
│                           ↓                                             │
│                    Discovery Lambda                                     │
│                           ↓                                             │
│                  Document Download Queue                                │
│                           ↓                                             │
│                    Download Lambda                                      │
│                           ↓                                             │
│                 Raw Documents S3 Bucket                                 │
│                           ↓                                             │
│                  Document Analysis Queue                                │
│                           ↓                                             │
│                     Analysis Lambda                                     │
│                           ↓                                             │
│                       Supabase                                          │
│                                                                         │
│  Supporting Services                                                    │
│                                                                         │
│  CloudWatch | IAM | Secrets Manager | Dead-Letter Queues                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 26. Main Architectural Benefit

The central design decision is to separate the workflow into independent stages connected by Amazon SQS.

This provides:

- Independent retries.
- Failure isolation.
- Independent scaling.
- Reliable processing.
- Partial job completion.
- Easier monitoring.
- Easier debugging.
- Reduced repeated work.
- Safer document storage.
- Better control over concurrency and costs.

If document analysis fails, the document remains stored in S3.

If downloading fails, document discovery does not need to run again.

If one document fails, other documents from the same website can still complete successfully.
```
# AWS Deployment Plan

## 1. Purpose and scope

This document describes how to deploy the current StonksInHand application to
AWS. It is a deployment plan, not an implementation record.

The plan assumes:

- AWS Region: `ap-southeast-2` (Sydney).
- The first environment is a low-traffic demo/staging environment.
- The application remains containerised.
- PostgreSQL data must survive application deployments.
- The public application is served over HTTPS on a real domain.
- The FastAPI API remains behind the Next.js `/api/*` proxy instead of being
  exposed as a separate public origin.

Production hardening and higher-availability changes are called out separately.

## 2. What is being deployed

The repository currently contains:

| Component | Current implementation | Important runtime needs |
|---|---|---|
| Frontend | Next.js 14 on Node 20 | Port 3000 and access to FastAPI |
| Backend | FastAPI/Uvicorn on Python 3.11 | Port 8000, Chromium/Playwright, FinBERT/PyTorch, outbound internet |
| Database | PostgreSQL 15 | Persistent relational storage and Alembic migrations |
| Scraping/processing | FastAPI startup hooks and background tasks | Outbound internet, temporary PDF storage, long execution time |
| External APIs | Reddit, Groq, Gemini legacy path, Yahoo Finance, ASX/company sites | Secrets and outbound HTTPS |

The backend image includes Chromium, Playwright Chromium, PyTorch, and a bundled
FinBERT model. It will therefore be much larger and use more memory than a
typical FastAPI image.

## 3. Deployment readiness findings

The application should not be deployed unchanged. The following items are
deployment blockers or material operational risks.

### P0: required before the first AWS deployment

1. **Run Next.js in production mode.**
   `docker-compose.yml` currently overrides the frontend command with
   `npm run dev`, and the frontend Dockerfile has no production `CMD`. The
   deployed container must run `npm run start` or a Next.js standalone server.

2. **Make the frontend image reproducible.**
   Commit a `package-lock.json`, use `npm ci`, pin the Node base image to a
   supported patch/digest, and add a production runtime stage. The current
   `npm install` without a lock file can produce different images from the same
   commit.

3. **Configure the API proxy for ECS.**
   Browser requests should use `NEXT_PUBLIC_API_BASE_URL=/api`. The Next.js
   rewrite and server-side API client should target
   `INTERNAL_API_URL=http://127.0.0.1:8000`. The rewrite configuration is
   evaluated during `next build`, so this value must be available at build time
   as well as at runtime.

4. **Separate migrations from web-server startup.**
   Remove `alembic upgrade head` from the long-running backend command. Run it as
   a one-off ECS task before updating the ECS service. This prevents multiple
   replicas from attempting the same migration and lets a failed migration stop
   the release.

5. **Remove long-running work from application startup.**
   `main.py` currently queues ticker seeding and Reddit seeding at startup.
   Deployments, auto-scaling, and task replacement could run these jobs more
   than once. Add explicit feature flags that disable both jobs in the web
   service, then invoke seeding through a one-off ECS task.

6. **Add deployment-grade health checks.**
   Keep a lightweight liveness endpoint and add a readiness endpoint that checks
   database connectivity. Add a frontend health route that does not depend on
   external APIs. Configure both ECS container health checks and the load
   balancer health check.

7. **Set production cookie and origin settings.**
   Use `SESSION_COOKIE_SECURE=true`, `SESSION_COOKIE_SAMESITE=lax`, and set
   `CORS_ORIGINS` to the final HTTPS origin. Keeping all browser traffic on one
   origin avoids cross-site cookie complexity.

8. **Define temporary-file behaviour.**
   Scraped PDFs are written to `/app/output`, but durable application data and
   extracted raw text are stored in PostgreSQL. For the first deployment, treat
   `/app/output` as scratch space and delete files after successful processing.
   If PDFs must be retained, upload them to S3 and store the S3 object key in the
   artifact metadata before launch.

### P1: required before a production launch

- Replace in-process FastAPI `BackgroundTasks` for scrapes with an SQS-backed
  worker. In-process work is lost if ECS replaces the task.
- Pin the FinBERT repository to an immutable revision instead of cloning its
  mutable default branch during every build.
- Pin the `uv` image and Git/Xet installer rather than downloading unpinned
  executable content during the Docker build.
- Remove the duplicated system Chromium or Playwright Chromium installation
  after verifying which executable the scrapers use.
- Add database connection validation, `pool_pre_ping`, explicit pool sizing,
  and PostgreSQL TLS (`sslmode=require`).
- Disable or protect `/docs`, `/redoc`, and any administrative/manual-write API
  endpoints in production.
- Add request-size limits, authentication rate limiting, and CSRF review for
  cookie-authenticated mutations.
- Add structured logs with request/correlation IDs. Do not log session tokens,
  API keys, credentials, or full sensitive request bodies.
- Run the web service with a non-root container user and a read-only root
  filesystem where Playwright and temporary output requirements permit it.

## 4. Recommended AWS architecture

```text
Internet
   |
Route 53 DNS
   |
Application Load Balancer + ACM certificate
   |  HTTPS :443
   v
ECS service on AWS Fargate
  One task revision, initially one running task
  +------------------------------------------------------+
  | Next.js container :3000                              |
  |   /api/* -> http://127.0.0.1:8000                   |
  |                                                      |
  | FastAPI container :8000 (not in the ALB target group)|
  |   FinBERT + Playwright + scraper                     |
  +------------------------------------------------------+
       |                  |                     |
       | TCP 5432         | HTTPS egress        | logs/metrics
       v                  v                     v
  RDS PostgreSQL     NAT Gateway/Internet   CloudWatch
  private subnets    external data/APIs     Logs + Alarms
       ^
       |
  Secrets Manager supplies DATABASE_URL and API keys

GitHub Actions --OIDC--> AWS
       |                  |
       v                  v
  ECR frontend        ECR backend
       \                  /
        \--> ECS task revision and deployment
```

Amazon ECS Fargate tasks use `awsvpc` networking, and containers in the same
task can communicate over `localhost`. This makes a two-container task a direct
fit for the existing Next.js proxy design. See the
[AWS Fargate task networking documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html).

### Why a single two-container task is recommended initially

- Only the frontend needs a public load-balancer target.
- The API can stay private and same-origin cookies continue to work.
- No service-discovery layer is required.
- Frontend and backend versions are released together, which matches the
  current repository and API coupling.
- It is simpler and cheaper for a proof of concept.

The trade-off is that frontend and backend scale together. Split them into
separate ECS services with ECS Service Connect only when load testing shows a
real need to scale them independently.

## 5. AWS resources

Create all resources as infrastructure as code. Terraform is recommended for
this repository, with remote state in an encrypted/versioned S3 bucket and state
locking enabled. AWS CDK is also acceptable if the team prefers TypeScript.
Do not build the permanent environment manually in the AWS console.

### Network

- One VPC across two Availability Zones.
- Two public subnets for the Application Load Balancer.
- Two private application subnets for ECS tasks.
- Two private database subnets for RDS.
- Internet Gateway for public ingress.
- NAT Gateway egress for ECS because the scrapers and external API clients need
  arbitrary internet access.
- Route tables scoped to each subnet tier.

For production, use a NAT Gateway in each Availability Zone. A demo environment
can use one NAT Gateway to reduce cost, accepting the single-AZ egress failure
mode. A still cheaper demo option is to place Fargate tasks in public subnets
with public IPs and restrict inbound traffic to the ALB security group; do not
use that profile for production user data.

### Security groups

| Security group | Inbound | Outbound |
|---|---|---|
| ALB | TCP 443 from the internet; TCP 80 only for HTTPS redirect | TCP 3000 to ECS task SG |
| ECS task | TCP 3000 from ALB SG only | TCP 5432 to RDS SG and HTTPS/DNS egress |
| RDS | TCP 5432 from ECS task SG only | Default response traffic |

Do not add a public inbound rule for backend port 8000 or database port 5432.

### Container registry

- One private ECR repository for `stonks-frontend`.
- One private ECR repository for `stonks-backend`.
- Enable image scanning and immutable tags.
- Tag each image with the Git commit SHA.
- Deploy by SHA tag or image digest, never `latest`.
- Add lifecycle rules that retain recent release images and delete old
  unreferenced images.

### ECS and Fargate

Start the demo environment with:

- Linux/x86-64 Fargate task.
- `2 vCPU` and `8 GiB` task memory as a conservative starting point.
- Approximate container shares: backend 1.5 vCPU/6 GiB and frontend
  0.5 vCPU/1 GiB, leaving task overhead.
- `30 GiB` ephemeral storage to allow for large image layers, Playwright, and
  temporary PDFs.
- Desired task count: `1` for demo/staging.
- Deployment circuit breaker with automatic rollback.
- ECS Exec disabled by default and enabled temporarily only for controlled
  diagnostics.
- CloudWatch Logs using separate log streams for frontend and backend.
- A health-check grace period long enough for the large backend image and
  readiness process, initially 180 seconds and then tuned from measurements.

Fargate provides 20 GiB by default and supports increasing task ephemeral
storage up to 200 GiB. Container image layers consume part of that allocation.
See [Fargate task storage](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-storage.html).

Do not reduce the initial memory estimate until a test run measures:

- steady-state memory after FinBERT is loaded;
- peak memory during sentiment analysis;
- peak memory while Chromium and PDF parsing run together;
- backend image pull/start time; and
- `/app/output` growth during a complete five-ticker seed.

For production, use at least two tasks across two Availability Zones, but only
after startup jobs have been removed from the web process and background jobs
are durable.

### Application Load Balancer, TLS, and DNS

- Public Application Load Balancer across both public subnets.
- Target group type `ip`, targeting frontend container port 3000.
- HTTP listener redirects to HTTPS.
- HTTPS listener uses an ACM certificate.
- Route 53 alias record points the application hostname to the ALB.
- ALB health check uses a dedicated frontend health route.
- Enable deletion protection and ALB access logs for production.

The backend is not registered with the load balancer. Browser requests to
`/api/*` first reach Next.js, which proxies them to the backend over
`127.0.0.1:8000`.

### RDS PostgreSQL

- Amazon RDS for PostgreSQL 15 initially, matching local Compose.
- Private DB subnet group; `publicly_accessible=false`.
- Demo: small Single-AZ burstable instance.
- Production: Multi-AZ instance sized from observed CPU, connections, storage,
  and latency.
- Encrypted General Purpose SSD storage with storage autoscaling.
- Automated backups and point-in-time recovery.
- Deletion protection and a final snapshot in production.
- Apply minor-version upgrades in a controlled maintenance window.
- Require TLS from the application.

Use an RDS security group that accepts port 5432 only from the ECS task security
group. AWS documents security-group-controlled RDS access in
[Controlling access with security groups](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Overview.RDSSecurityGroups.html).

### Secrets and configuration

Store sensitive values in AWS Secrets Manager and inject them using the ECS task
definition `secrets` field. AWS recommends Secrets Manager or Systems Manager
Parameter Store for ECS secret material; see
[Passing sensitive data to ECS containers](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specifying-sensitive-data.html).

Secrets:

- `DATABASE_URL` using the private RDS endpoint and `sslmode=require`
- `GROQ_API_KEY`
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `GEMINI_API_KEY` only if the legacy Gemini integration is enabled

Non-secret environment configuration:

| Variable | Deployment value |
|---|---|
| `INTERNAL_API_URL` | `http://127.0.0.1:8000` |
| `NEXT_PUBLIC_API_BASE_URL` | `/api` |
| `FINBERT_MODEL` | `/app/finbert` |
| `GROQ_MODEL` | Pin the approved model identifier |
| `GEMINI_MODEL` | Pin only if enabled |
| `CORS_ORIGINS` | `https://<application-hostname>` |
| `SESSION_COOKIE_SECURE` | `true` |
| `SESSION_COOKIE_SAMESITE` | `lax` |
| `SESSION_EXPIRE_DAYS` | `7`, or the agreed policy |
| `SEED_TICKERS` | Empty in the web service |
| `REDDIT_SEED_SUBREDDIT` | `ASX` for a one-off/worker task |
| `REDDIT_SEED_LIMIT` | Agreed bounded job value |

Secret rotation is not visible to a running container automatically. Rotate the
secret, register a new task definition revision if required, and force a new ECS
deployment.

### IAM

Use separate least-privilege roles:

- **ECS execution role:** pull the two ECR images, write CloudWatch logs, and
  retrieve only the named Secrets Manager secrets.
- **ECS task role:** no AWS permissions initially. Add access to only the
  application S3 prefix if durable PDF storage is implemented.
- **Migration/seed task role:** only the permissions specifically required by
  those jobs.
- **GitHub deployment role:** assumed through GitHub OIDC and limited to the
  repository, branch/environment, ECR repositories, ECS resources, and required
  infrastructure actions.

Do not store AWS access keys in GitHub secrets. Scope the OIDC trust policy to
this repository and its protected deployment environment. AWS explicitly
requires the GitHub OIDC `sub` condition to be constrained; see
[Creating an OIDC-federated IAM role](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html).

### Object storage

S3 is not required if downloaded PDFs are temporary and deleted after parsing.
If retention is required:

- Create a private, encrypted, versioned S3 bucket.
- Block all public access.
- Use object keys such as
  `announcements/<ticker>/<published-date>/<content-hash>.pdf`.
- Grant the task role access only to the relevant bucket/prefix.
- Store the object key, source URL, checksum, and ingestion time in PostgreSQL.
- Add an S3 lifecycle policy for the agreed retention period.

Do not use EFS merely to preserve the current `/app/output` directory. S3 is a
better fit for immutable source PDFs.

## 6. Application changes

### Frontend image

Recommended result:

1. Generate and commit `package-lock.json`.
2. Update the Dockerfile to use `npm ci`.
3. Supply `INTERNAL_API_URL=http://127.0.0.1:8000` while running `next build`.
4. Use Next.js standalone output or copy only production dependencies and build
   artifacts into a clean runtime stage.
5. Add `CMD ["npm", "run", "start"]` or the standalone equivalent.
6. Run as a non-root Node user.
7. Add a dedicated health route.

### Backend image

Recommended result:

1. Pin all base images by supported version and preferably digest.
2. Pin the FinBERT model revision.
3. Replace the remote installer pipe with a pinned, checksummed build input.
4. Verify whether system Chromium or Playwright Chromium is required, then keep
   only one.
5. Add a non-root runtime user and writable scratch/output paths.
6. Run Uvicorn without the Alembic command:

   ```text
   python -m uvicorn main:app --host 0.0.0.0 --port 8000
   ```

7. Start with one worker. Multiple Uvicorn workers would each load a FinBERT
   model and can multiply memory use.
8. Add readiness that verifies PostgreSQL connectivity.
9. Warm FinBERT deliberately during readiness or immediately after deployment,
   and measure the effect before making it mandatory.

### Startup and background jobs

Refactor the current startup hooks into explicit commands, for example:

```text
python -m alembic upgrade head
python -m app.jobs.seed --tickers ANZ,CBA,BHP,WES,CSL
python -m app.jobs.seed_reddit --subreddit ASX --limit 50
```

The exact module names can differ, but each command must:

- return a non-zero exit code on failure;
- be safe to retry;
- log a start time, completion time, item counts, and failures;
- avoid starting an HTTP server; and
- prevent duplicate work through database uniqueness/idempotency.

For the first demo, run these as manual one-off ECS tasks. For production,
invoke scheduled jobs with EventBridge Scheduler and use SQS plus a dedicated
worker service for user-triggered jobs.

## 7. Infrastructure-as-code layout

Suggested repository structure:

```text
infra/
  terraform/
    modules/
      network/
      ecr/
      rds/
      ecs/
      observability/
    environments/
      staging/
      production/
```

Each environment should have separate state, secrets, database, log groups, ECS
service, and DNS hostname. Do not make staging share the production database.

Terraform outputs should include:

- application URL;
- ECS cluster and service names;
- ECR repository URLs;
- migration task definition family;
- RDS endpoint without credentials; and
- CloudWatch dashboard name.

## 8. CI/CD workflow

Use GitHub Actions with short-lived AWS credentials obtained through OIDC.

### Pull request checks

1. Backend unit/integration tests.
2. Frontend production build.
3. Docker builds for both production targets.
4. Dependency and container vulnerability scans.
5. Terraform formatting, validation, and plan.
6. Fail if credentials or `.env` files are included in the build context.

### Deployment to staging

1. Merge to the protected deployment branch.
2. Authenticate to AWS through GitHub OIDC.
3. Build both images from the same Git commit.
4. Push commit-SHA-tagged images to ECR.
5. Apply reviewed infrastructure changes.
6. Register a one-off migration task using the new backend image.
7. Run the migration task and wait for a successful exit code.
8. Register the web task definition using the exact two image digests.
9. Update the ECS service.
10. Wait for ECS steady state and ALB health.
11. Run smoke tests.
12. Mark the Git commit and task revision as the deployed release.

### Production promotion

Promote previously tested image digests rather than rebuilding them. Require a
protected GitHub environment approval, a reviewed Terraform plan, a current RDS
backup, and a migration compatibility review.

Enable the ECS deployment circuit breaker with rollback. AWS documents that it
can stop a deployment that cannot reach steady state and roll back to the last
completed deployment; see
[ECS deployment circuit breaker](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html).

## 9. Database migration strategy

Use an expand-and-contract approach:

1. Take or verify a backup before risky schema changes.
2. Deploy additive/backward-compatible migrations first.
3. Run the migration as a one-off ECS task.
4. Deploy application code that can work with both old and new schema states.
5. Remove old columns/constraints only in a later release.

Application rollback does not automatically reverse a database migration.
Every release must state whether its migration is backward compatible and how
to recover if it fails. Do not automatically run Alembic downgrade in the
deployment pipeline.

## 10. Observability and alarms

Create:

- CloudWatch log groups for frontend, backend, migrations, and scheduled jobs;
- 14-day retention for demo and an agreed retention period for production;
- a dashboard for ALB, ECS, and RDS;
- alarms for:
  - ALB unhealthy hosts;
  - sustained ALB 5xx responses;
  - ECS task restarts and failed deployments;
  - ECS CPU and memory pressure;
  - Fargate ephemeral-storage pressure;
  - RDS CPU, free storage, connections, and low freeable memory;
  - migration or scheduled-job failure; and
  - Secrets Manager or ECR permission failures visible in stopped-task reasons.

Send production alarms to an owned notification channel. Avoid alerting on a
single transient scraper failure; use a threshold and a dead-letter queue once
SQS workers exist.

## 11. Validation and cutover checklist

### Before deployment

- [ ] Frontend production image starts with `npm start`/standalone server.
- [ ] Both images build from a clean checkout.
- [ ] Compose-based automated tests pass.
- [ ] No secrets are present in Git history, Docker layers, build arguments, or
      logs.
- [ ] RDS restore procedure has been tested in staging.
- [ ] Startup seeding is disabled in the web service.
- [ ] Migration task succeeds against a fresh staging database.
- [ ] Backend memory is measured with FinBERT and Chromium active.
- [ ] `/app/output` retention/cleanup behaviour is confirmed.

### Smoke tests after deployment

- [ ] `GET /` returns the Next.js application over HTTPS.
- [ ] HTTP redirects to HTTPS.
- [ ] `GET /api/health` returns success.
- [ ] `GET /api/tickers` returns database-backed data.
- [ ] Sign-up sets a `Secure`, `HttpOnly` session cookie.
- [ ] Sign-in, `/api/auth/me`, sign-out, and session expiry work.
- [ ] Watchlist reads and writes persist after an ECS task replacement.
- [ ] One sentiment request loads/runs FinBERT successfully.
- [ ] One supported ticker scrape can use Chromium and write/process a PDF.
- [ ] External Reddit/Groq calls work without exposing their credentials.
- [ ] Frontend, backend, and ALB logs are available.
- [ ] An intentionally bad task revision is rolled back in staging.

### Production exit criteria

- [ ] Two healthy tasks run across two Availability Zones.
- [ ] RDS is Multi-AZ with backups, deletion protection, and restore evidence.
- [ ] Long-running jobs use a durable queue/worker path.
- [ ] Public API documentation and administrative endpoints are protected.
- [ ] WAF/rate-limit requirements have been reviewed.
- [ ] Load, failure, and recovery tests meet agreed targets.

## 12. Rollback and recovery

Application rollback:

1. Stop or allow the circuit breaker to fail the unhealthy deployment.
2. Restore the last known-good ECS task definition revision/image digests.
3. Confirm ALB health and rerun smoke tests.

Database recovery:

1. Prefer a forward fix for a backward-compatible migration.
2. For destructive corruption, restore RDS to a new instance from
   point-in-time recovery.
3. Validate the restored database before changing the application secret or
   endpoint.
4. Preserve the failed database until the incident is understood.

Job recovery:

- One-off seed jobs must be idempotent and safe to rerun.
- Once SQS is introduced, configure retry limits and a dead-letter queue.
- Do not rely on files left on Fargate ephemeral storage for recovery.

## 13. Recommended implementation order

1. Fix and verify the two production Docker images.
2. Add health/readiness endpoints and production configuration.
3. extract migrations and seed operations into one-off commands.
4. Decide whether PDFs are scratch data or durable S3 objects.
5. Add Terraform for ECR, networking, RDS, secrets, ECS, ALB, DNS, and logging.
6. Deploy an empty staging environment.
7. Build and push commit-addressed images.
8. Run migrations, deploy the service, and run smoke tests.
9. Benchmark memory, startup time, storage, and scrape duration; right-size the
   task and RDS instance.
10. Add GitHub OIDC CI/CD and automated rollback validation.
11. Add SQS workers and multi-AZ/high-availability settings before production.

## 14. Decisions still needed

The team must confirm:

- the final domain or subdomain;
- whether the target is a disposable class demo, persistent staging, or
  production;
- acceptable monthly AWS budget;
- whether source PDFs must be retained and for how long;
- availability and recovery targets;
- whether Reddit/Groq/Gemini use is allowed for the deployed environment;
- the required scraping schedule;
- log/data retention requirements; and
- who owns production alarms, secret rotation, backups, and incident response.

These decisions affect cost and hardening, but they do not block implementing
the P0 image, configuration, migration, and startup-job changes.
