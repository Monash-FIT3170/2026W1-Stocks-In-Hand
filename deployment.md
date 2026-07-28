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

---

## 27. Repository-Specific Implementation Plan

This section maps the target architecture above to the code that currently
exists in this repository. It is the implementation sequence to follow; it does
not replace the event-driven architecture in Sections 1–26.

### 27.1 Current fit assessment

| Target component | Reusable code | Gap to close |
|---|---|---|
| S3/CloudFront frontend | Next.js pages and components | The app is not currently a static export. Several pages use server-side fetching, dynamic routes, search parameters, and a Next.js rewrite. |
| API Gateway/backend Lambda | FastAPI routes, schemas, CRUD, auth, SQLAlchemy | Add a Lambda ASGI adapter, split API-only dependencies, and use serverless-safe database pooling. |
| Website queue | `ScrapeRun`, ticker registry, scrape routes | The current `/scrape/{ticker}` endpoint runs an in-process background task instead of publishing a job message. |
| Discovery Lambda | Five company scraper adapters | The public scraper contract separates discovery/download, but some implementations still download inside `fetch_announcements`. |
| Download Lambda | `Announcement` metadata and HTTP/Playwright download logic | Move downloading out of discovery, stream to S3, validate files, calculate checksums, and publish analysis messages. |
| Analysis Lambda | PDF extraction, classifier, FinBERT service, storage layer | Read from S3 instead of `/app/output`, package the large ML dependencies for Lambda, and write stage state/results idempotently. |
| Supabase | PostgreSQL-compatible SQLAlchemy and Alembic schema | Use the Supabase serverless pooler and extend existing tables with per-document stage state and S3 metadata. |
| EventBridge | Startup seeding logic | Replace startup hooks with an explicit scheduled job creator. |

The current application supports five configured ASX sources (`ANZ`, `CBA`,
`BHP`, `WES`, and `CSL`) and primarily processes PDFs. Generic website
submission and support for DOCX, XLSX, CSV, TXT, and HTML are later increments,
not capabilities that already exist.

### 27.2 Selected deployment shape

Use `ap-southeast-2` unless the Supabase project, data-residency requirement, or
team policy requires another region.

```text
app.example.com
        |
        v
CloudFront
  | default behaviour                 | /api/*
  v                                   v
Private frontend S3 bucket       API Gateway HTTP API
                                      |
                                      v
                                FastAPI Lambda
                                  |         |
                                  v         v
                              Supabase   Website SQS
                                             |
                                             v
                                      Discovery Lambda
                                             |
                                             v
                                      Download SQS
                                             |
                                             v
                                       Download Lambda
                                         |         |
                                         v         v
                                  Raw document S3  Analysis SQS
                                                       |
                                                       v
                                                Analysis Lambda
                                                       |
                                                       v
                                                   Supabase
```

CloudFront should be the only browser-facing origin:

- The default behaviour serves the static frontend from the private S3 bucket.
- The `/api/*` behaviour forwards API traffic to API Gateway with caching
  disabled and cookies, query strings, required headers, and all API methods
  forwarded.
- API Gateway or the Lambda adapter must strip the `/api` base path before
  FastAPI route matching.
- This preserves the frontend's existing `/api` base URL and keeps session
  cookies same-origin.

Use CloudFront Origin Access Control, not a public S3 website endpoint. AWS
recommends OAC for private S3 origins:
[Restrict access to an Amazon S3 origin](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html).

### 27.3 Mandatory technical spikes

Complete these measurements before committing the workload to Lambda:

1. Build a Lambda-compatible analysis container containing PyTorch,
   Transformers, pypdf, and the pinned FinBERT model.
2. Record its uncompressed size, cold-start time, warm execution time, peak
   memory, and `/tmp` usage for representative small, average, and largest PDFs.
3. Run each Playwright scraper in a Lambda-compatible discovery image and
   measure cold start, browser startup, duration, and memory.
4. Verify that every discovered URL can be downloaded in a separate invocation.
   ANZ, CBA, and WES currently reuse browser context or click-based downloads,
   so this separation is not yet guaranteed.
5. Load-test concurrent Lambda connections through Supabase's transaction-mode
   pooler.

Lambda has a 15-minute maximum invocation time, a 10 GB maximum uncompressed
container image, up to 10,240 MB memory, and configurable `/tmp` storage from
512 MB to 10,240 MB. These are hard design constraints, not values to discover
after deployment. See
[AWS Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html).

Go/no-go rules:

- If analysis cannot reliably finish inside 15 minutes with at least 20% time
  headroom, retain the SQS/S3 stages but consume the analysis queue with an ECS
  Fargate worker.
- If a source requires a live browser session across discovery and download,
  refactor that source adapter so the download Lambda can recreate the session.
  Do not put cookies or authentication tokens into SQS messages.
- If static export would remove required product behaviour, use a managed
  Next.js runtime for the frontend and record that as an approved deviation
  from Section 3.

### 27.4 Phase 0: repository and dependency preparation

1. Add and commit a frontend `package-lock.json`.
2. Replace `npm install` with `npm ci` in builds.
3. Split backend requirements into deployable groups:
   - API: FastAPI, Mangum, SQLAlchemy, psycopg2, auth/validation packages.
   - Discovery: Playwright/Chromium, HTTP client, shared scraper code.
   - Download: HTTP client, AWS SDK, file-validation utilities, and only the
     browser dependencies proven necessary.
   - Analysis: PyTorch, Transformers, pypdf, AWS SDK, and shared parsing code.
4. Pin the FinBERT repository to an immutable model revision.
5. Pin base images and the model/Xet download mechanism to immutable versions
   or checksums.
6. Add a shared package for message schemas, status constants, URL validation,
   database helpers, structured logging, and idempotency.
7. Keep local Docker Compose for development and integration tests; it is not
   the production topology.

Exit criteria:

- Clean-checkout frontend and backend tests pass.
- Each Lambda package/image builds independently.
- No Lambda contains dependencies belonging only to another stage.

### 27.5 Phase 1: static frontend conversion

The current frontend cannot be copied to S3 as-is. Next.js static export does
not support rewrites or dynamic routes without `generateStaticParams`, and
server components execute their fetches during the build. See
[Next.js static export limitations](https://nextjs.org/docs/app/guides/static-exports).

Make these changes:

1. Set `output: "export"` and preferably `trailingSlash: true` in
   `frontend/next.config.js`.
2. Remove the production reliance on the Next.js `/api` rewrite.
3. Build with `NEXT_PUBLIC_API_BASE_URL=/api`.
4. Convert the announcements page from build-time/server-side data fetching to
   a client component that fetches after page load.
5. Convert ticker summary, news, and deep-dive pages to client-side data
   fetching, or add `generateStaticParams` for every supported ticker. Client
   fetching is preferred if ticker symbols will change without a frontend
   rebuild.
6. Keep sign-in, sign-up, sign-out, search, watchlist, and session checks in
   client components.
7. Replace user-facing “backend on port 8000” errors with deployment-neutral
   messages.
8. Confirm direct navigation and refresh for:
   - `/`
   - `/announcements/`
   - `/search/`
   - `/sign-in/`
   - `/watchlist/`
   - every supported ticker route and subroute.
9. Add a static `404.html` and CloudFront routing/error behaviour compatible
   with the generated trailing-slash paths.
10. Add long-lived immutable caching for hashed assets and short/no-cache
    behaviour for HTML.

Frontend deployment:

```text
npm ci
npm run build
aws s3 sync out/ s3://<frontend-bucket>/ --delete
aws cloudfront create-invalidation --distribution-id <id> --paths "/*"
```

Use commit-addressed build artifacts and deploy the same tested artifact to
production rather than rebuilding it.

### 27.6 Phase 2: Supabase schema and connection changes

The existing schema should be extended instead of creating duplicate concepts.

| Architecture concept | Existing table(s) | Required change |
|---|---|---|
| Scraping jobs | `scrape_runs` | Add requester/source URL, stage counts, queued/completed timestamps, stable status values, idempotency key, and last error. |
| Websites | `information_platforms` | Use `base_url` and `scrape_config`; add last/next scrape timestamps and unique canonical URL/domain rules if generic sites are introduced. |
| Documents | `artifacts` | Add `scrape_run_id`, file name/type/size/checksum, S3 bucket/key, download status, analysis status, stage timestamps, and last error. |
| Analysis results | `artifact_sentiments`, `artifact_summaries`, `artifact_topics`, `extracted_facts` | Add/confirm model name, model revision, analysis version, confidence, and uniqueness rules. |
| Processing attempts | New `processing_attempts` table | Store job/document/stage/attempt/status/error/start/end for audit and retries. |

Add database constraints for:

- one canonical document URL per scrape run;
- one stored content checksum per agreed deduplication scope;
- one completed analysis per artifact, analysis type, model revision, and
  analysis version; and
- one idempotency key per processing stage.

Lambda runtime connections should use Supabase's transaction-mode Supavisor
pooler on port 6543. Supabase identifies transaction mode as the appropriate
option for serverless/temporary clients:
[Supabase database connections](https://supabase.com/docs/guides/database/connecting-to-postgres).

For SQLAlchemy Lambda handlers:

- use `NullPool` or a deliberately tiny pool;
- enable `pool_pre_ping`;
- use short connection and statement timeouts;
- close every session in `finally`;
- do not assume a connection remains valid after an execution environment is
  frozen; and
- disable prepared statements if the chosen driver/configuration would use
  them through transaction mode.

Use a separate migration connection suitable for Alembic. Run migrations as a
CI/CD release step, not from an API request or every Lambda cold start.

### 27.7 Phase 3: backend API Lambda

Reuse the FastAPI application for synchronous application APIs:

1. Add Mangum or an equivalent ASGI-to-Lambda adapter.
2. Create a Lambda entry point separate from the local Uvicorn entry point.
3. Package only API dependencies; do not include FinBERT, Playwright, or
   Chromium.
4. Configure an API Gateway HTTP API proxy integration for the required
   FastAPI routes.
5. Add the job endpoints defined in Section 4:
   - `POST /scraping-jobs`
   - `GET /scraping-jobs`
   - `GET /scraping-jobs/{jobId}`
   - `POST /scraping-jobs/{jobId}/retry`
   - document/result read endpoints as required by the UI.
6. Replace `/scrape/{ticker}` background execution with:
   - authenticated/authorised request validation;
   - a `scrape_runs` row committed as `QUEUED`;
   - an idempotent website-queue message; and
   - an HTTP `202 Accepted` response containing the job ID.
7. Remove ticker and Reddit auto-seeding from FastAPI startup.
8. Keep a lightweight `/health` endpoint that does not load FinBERT.
9. Protect or disable `/docs` and `/redoc` in production.

Authentication requirements:

- Route browser API traffic through CloudFront `/api/*` so the session cookie is
  same-origin.
- Set `SESSION_COOKIE_SECURE=true`, `HttpOnly=true`, and the agreed SameSite
  policy.
- Forward `Cookie` and `Set-Cookie` through CloudFront/API Gateway.
- Disable caching on all authenticated API behaviours.
- Add CSRF protection for cookie-authenticated write operations.
- Add API Gateway throttling and AWS WAF rate-based rules for auth and job
  creation endpoints.

### 27.8 Phase 4: queue contracts and state machine

Define versioned Pydantic message schemas. Every message should include:

```json
{
  "schemaVersion": 1,
  "jobId": "uuid",
  "documentId": "uuid-or-null",
  "stage": "DISCOVERY|DOWNLOAD|ANALYSIS",
  "attemptCorrelationId": "uuid",
  "requestedAt": "ISO-8601 UTC timestamp"
}
```

Stage-specific fields:

- Discovery: `platformId`, `ticker`, canonical source URL.
- Download: document ID, source URL, document URL, expected type, and
  non-sensitive adapter metadata.
- Analysis: document ID, S3 bucket, object key, checksum, content type, and
  analysis version.

Rules:

- Do not include secrets, cookies, raw document content, or full extracted text
  in SQS.
- Validate every message at the handler boundary.
- Treat SQS delivery as at least once.
- Start each handler with a database idempotency/status check.
- Commit the completed database state before acknowledging success.
- Publish the next-stage message with a deterministic deduplication record or
  transactional outbox so a database commit followed by an SQS failure can be
  recovered.

### 27.9 Phase 5: discovery Lambda

Refactor the scraper interface so discovery returns metadata only:

```text
discover(source) -> list[DiscoveredDocument]
download(document) -> stored S3 object
```

For each company adapter:

1. Move all file writes and downloads out of discovery.
2. Return title, publication date, direct/source URL, ticker, expected file
   type, and adapter metadata.
3. Canonicalise and deduplicate URLs.
4. Upsert artifact/document rows as `QUEUED_FOR_DOWNLOAD`.
5. Publish one download message per document.
6. Update the scrape run's discovery counts/status.

Initial controls:

- allowlist only the five implemented source domains;
- SQS batch size `1`;
- reserved/maximum concurrency `1–2`;
- timeout around five minutes, based on measurements;
- Chromium-compatible container image;
- bounded page count, link count, redirects, and navigation time;
- structured logs containing job ID, source/ticker, stage, attempt, and
  duration.

Generic user-supplied websites should not be enabled until the SSRF controls in
Section 18 are implemented and security-tested.

### 27.10 Phase 6: download Lambda

Implement one document per SQS record:

1. Revalidate the URL and every redirect target.
2. Resolve DNS and reject loopback, link-local, private, reserved, metadata, and
   unsupported addresses before every request/redirect.
3. Apply per-domain timeouts, concurrency, and a clear user agent.
4. Stream the response while enforcing a maximum byte count.
5. Verify status, content type, magic bytes, and supported extension.
6. Calculate SHA-256 while streaming.
7. Check the database for duplicate content.
8. Write to the private raw-document S3 bucket using a deterministic key.
9. Record S3 version ID/ETag, checksum, size, type, and `DOWNLOADED` state.
10. Publish the analysis message.

Prefer streaming directly to S3. Use `/tmp` only when a source/browser download
requires it, and delete temporary data before returning.

For sources needing browser context, implement a source-specific download
strategy that recreates the context from non-secret metadata. A failed download
must never require discovery to run again.

### 27.11 Phase 7: analysis Lambda

Create an analysis-only Lambda container:

- Use an AWS Lambda Python base image or include the Lambda runtime interface
  client in a compatible custom image.
- Do not include Playwright or Chromium.
- Copy a pinned FinBERT model into the image.
- Read the source object from S3.
- Use `/tmp` only for bounded local processing.
- Extract and chunk PDF text.
- Run the existing FinBERT distribution/aggregation logic.
- Store raw text and metadata in `artifacts` and results in the existing
  analysis tables.
- Record model revision and analysis version.
- Mark the document complete only after all required result writes commit.

Lambda container images must be read-only except for `/tmp` and must implement
the Lambda runtime API. See
[Creating Lambda container images](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html).

Initial configuration, subject to the spike:

- batch size `1`;
- memory `6–10 GB`;
- timeout below 15 minutes with operational headroom;
- `/tmp` sized to the maximum accepted document plus extraction overhead;
- reserved/maximum concurrency `1–2` to protect Supabase and cost;
- no VPC attachment unless a future private dependency requires it.

Keeping these Lambdas outside a customer VPC preserves their default outbound
internet connectivity to Supabase and external model APIs and avoids a NAT
Gateway. If VPC attachment is introduced later, explicitly provide working
internet egress.

### 27.12 Phase 8: S3, SQS, DLQs, and EventBridge

Raw document bucket:

- Block Public Access.
- Use SSE-S3 initially or SSE-KMS if policy requires customer-managed keys.
- Enable versioning.
- Enforce TLS in the bucket policy.
- Use keys such as
  `raw-documents/<job-id>/<document-id>/<sha256>.<extension>`.
- Add lifecycle rules for the approved retention period.
- Never serve raw documents through the frontend bucket.
- Issue short-lived signed URLs only after an authorised API request.

Create three standard queues and three DLQs. Suggested initial settings:

| Queue | Lambda timeout | Visibility timeout | Batch | Max receives |
|---|---:|---:|---:|---:|
| Website discovery | 5 minutes | 30 minutes | 1 | 5 |
| Document download | 5 minutes | 30 minutes | 1 initially | 5 |
| Document analysis | 15 minutes | 90 minutes | 1 | 5 |

Tune these values from measured p95 duration. AWS recommends an SQS visibility
timeout of at least six times the Lambda timeout and a `maxReceiveCount` of at
least five:
[Configuring SQS event sources for Lambda](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html).

Enable `ReportBatchItemFailures` before increasing a batch size above one so a
single failed record does not replay successful records. AWS documents the
at-least-once and partial-batch behaviour in
[Using Lambda with SQS](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html).

EventBridge Scheduler should invoke a small job-creation Lambda. It must create
the same database record and website-queue message as the API path. Do not
invoke discovery directly and do not keep the current FastAPI startup seeds.

### 27.13 Phase 9: infrastructure as code

Use AWS SAM for the serverless application and native CloudFormation resources
inside the same templates where SAM has no higher-level resource. Split stacks
only where lifecycle or permissions justify it.

Suggested layout:

```text
infra/
  samconfig.toml
  template.yaml
  parameters/
    dev.json
    staging.json
    production.json
backend/
  lambdas/
    api/
    discovery/
    download/
    analysis/
    scheduled_job/
  shared/
frontend/
```

The template must define:

- Lambda functions, versions/aliases, log groups, and reserved concurrency;
- API Gateway HTTP API and throttling/access logs;
- queues, DLQs, encryption, redrive policies, and event-source mappings;
- raw and frontend S3 buckets;
- CloudFront origins, behaviours, OAC, cache/origin-request policies, security
  headers, certificate, and DNS records;
- EventBridge schedules;
- Secrets Manager references;
- least-privilege IAM roles per Lambda;
- CloudWatch alarms and dashboards;
- AWS Budgets alerts; and
- environment-specific names/tags.

Use separate dev, staging, and production stacks, buckets, queues, secrets, and
Supabase configurations. Never share production queues or data with staging.

### 27.14 Phase 10: secrets and IAM

Store these in Secrets Manager:

- Supabase Lambda runtime connection string;
- separate migration connection string if required;
- Groq API key;
- Reddit client ID and secret;
- Gemini key only while the legacy integration is enabled.

Use separate execution roles:

- API: read its database/auth secrets and send only to the website queue.
- Discovery: consume website queue, send download queue, and read its database
  secret.
- Download: consume download queue, write only the raw-document bucket prefix,
  send analysis queue, and read its database secret.
- Analysis: consume analysis queue, read raw documents, read model/API secrets,
  and access the database.
- Scheduled job: send website queue and access only the job-creation database
  path/secret.

No Lambda should have wildcard administrator access. Queue messages and logs
must never contain secret values.

### 27.15 Phase 11: CI/CD

Use GitHub Actions with AWS OIDC; do not store long-lived AWS access keys.

Pull request pipeline:

1. Run backend unit and database integration tests.
2. Run frontend tests and a production static export.
3. Validate message-contract and idempotency tests.
4. Build all Lambda zip/container artifacts.
5. Run `sam validate` and a change-set preview.
6. Scan dependencies, Lambda images, and IaC.
7. Run scraper contract tests proving discovery performs no downloads.

Staging deployment:

1. Build immutable artifacts once and tag images with the Git commit SHA.
2. Apply backward-compatible Alembic migrations.
3. Deploy the SAM/CloudFormation change set.
4. Publish Lambda versions and move staging aliases.
5. Upload the tested frontend `out/` artifact to its S3 bucket.
6. Invalidate changed CloudFront paths.
7. Run end-to-end smoke tests.
8. Run one real scrape per supported source with conservative limits.
9. Verify S3 object, database state transitions, queue drain, and logs.

Production promotion:

- Promote the exact tested image digests and frontend artifact.
- Require a protected-environment approval.
- Review the CloudFormation change set and database migration.
- Use Lambda aliases for rapid code rollback.
- Do not automatically reverse database migrations; use expand-and-contract
  migrations and forward fixes.

### 27.16 Monitoring, alarms, and operating runbooks

Use structured JSON logs with:

```text
correlationId
jobId
documentId
stage
attempt
sourceDomain
status
durationMs
errorCode
```

Do not log full document text, credentials, cookies, or session tokens.

Create alarms for:

- each DLQ having one or more visible messages;
- age of oldest message breaching the stage service-level objective;
- sustained queue growth;
- Lambda errors, throttles, duration near timeout, and concurrency saturation;
- API Gateway 4xx/5xx and latency;
- Supabase connection failures;
- S3 access-denied or failed writes; and
- unexpected spend.

Write and test runbooks for:

- replaying one DLQ message after correcting its cause;
- retrying one document stage without replaying earlier stages;
- disabling one source/schedule;
- rotating a secret and refreshing Lambda environments;
- rolling back Lambda aliases and the frontend;
- restoring database data; and
- handling a malicious/invalid downloaded file.

### 27.17 Test strategy

Required automated tests:

- URL canonicalisation and SSRF blocking, including redirects and DNS rebinding
  scenarios;
- file type, magic byte, maximum size, corrupt file, and zip-bomb rejection;
- duplicate SQS delivery at every stage;
- database commit succeeds but next queue publish fails;
- partial batch failure;
- stale `IN_PROGRESS` recovery;
- duplicate URL and duplicate checksum handling;
- analysis version/model revision idempotency;
- cookie auth through the CloudFront `/api/*` path;
- static deep-link refreshes;
- Supabase connection exhaustion and recovery; and
- Lambda timeout/memory behaviour with representative files.

Staging failure tests:

- force each Lambda to fail and verify only its stage retries;
- exhaust retries and verify the correct DLQ/alarm;
- replay the DLQ message and verify no duplicate artifact/result;
- deploy an invalid Lambda version and verify alias rollback;
- delete a warm database connection and verify reconnection; and
- verify a failed analysis never causes another download.

### 27.18 Release acceptance criteria

The first staging release is complete when:

- [ ] The frontend is a clean static export served only through CloudFront.
- [ ] `/api/*` reaches FastAPI through API Gateway and the Lambda adapter.
- [ ] Sign-up, sign-in, `/auth/me`, sign-out, and secure session cookies work.
- [ ] Creating a scrape returns `202` and a durable job ID.
- [ ] Each supported source publishes discovery results without downloading.
- [ ] Each document is downloaded once logically, validated, hashed, and stored
      privately in S3.
- [ ] Analysis reads from S3 and stores versioned results in Supabase.
- [ ] Duplicate deliveries do not create duplicate rows or analysis work.
- [ ] Each stage retries independently and moves exhausted messages to its own
      DLQ.
- [ ] Status counts and partial completion are correct.
- [ ] CloudWatch logs, metrics, alarms, and correlation IDs work end to end.
- [ ] Measured Lambda duration, memory, image, and `/tmp` use have safe
      headroom.
- [ ] Infrastructure can be recreated from source using SAM/CloudFormation.

Production is additionally blocked until:

- [ ] Raw-document retention and deletion policy is approved.
- [ ] Source authorisation/terms and request-rate policy are approved.
- [ ] SSRF, file validation, auth, CSRF, and rate-limit review is complete.
- [ ] Supabase backups/recovery and migration rollback procedures are tested.
- [ ] Ownership exists for alarms, DLQs, secrets, database, and incidents.
- [ ] Load, cost, recovery-time, and recovery-point targets are met.

### 27.19 Implementation order

1. Complete the Lambda viability spikes.
2. Add locked/split dependencies and shared contracts.
3. Add the database migration for durable stage state and idempotency.
4. Adapt FastAPI to API Gateway/Lambda and replace in-process scrape triggers.
5. Convert Next.js to a static, client-fetching frontend.
6. Refactor all five scrapers into discovery-only adapters.
7. Implement and test the download Lambda and raw-document S3 storage.
8. Implement and benchmark the analysis Lambda.
9. Add queues, DLQs, EventBridge, IAM, secrets, alarms, and CloudFront in SAM.
10. Add OIDC CI/CD and deploy staging.
11. Run end-to-end, failure, security, and cost tests.
12. Promote to production only after all production acceptance criteria pass.

### 27.20 Decisions required from the team

Confirm before implementation:

- AWS account and final region;
- domain/subdomain and DNS ownership;
- Supabase project/region/tier and backup policy;
- whether PDFs are retained, and for how long;
- maximum document size and page count;
- whether only the five current sources are in scope for release one;
- whether document types other than PDF are required;
- scraping schedules and per-domain rate limits;
- whether Groq, Reddit, and Gemini are approved in each environment;
- job and document status retention;
- target monthly AWS/Supabase budget;
- availability, processing-time, recovery-time, and recovery-point objectives;
  and
- named owners for operations, security, database, and source compliance.
