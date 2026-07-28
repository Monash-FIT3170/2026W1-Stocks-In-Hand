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