# Code Review Recommendations — `feature/86d2xrmc2-Deployment`

Scope: full review of the branch that introduces the AWS Lambda/SQS/S3/CloudFront staging
deployment (157 files changed, ~10,300/-3,370 lines vs `main`), cross-checked against the
design docs (`deployment.md`, `infra/README.md`) and the deployed infrastructure-as-code
(`infra/template.yaml`, `infra/bootstrap.yaml`, `infra/github-oidc.yaml`) and CI workflows
(`.github/workflows/*.yml`).

**Overall assessment:** the new pipeline code (`backend/lambdas/*`, `app/crud/scrape_run.py`,
`app/messages.py`, `app/sources.py`) and the SAM template are well-designed, internally
consistent, and closely match the design docs. IAM scoping, budget controls, OIDC trust
policy, the two-person change-set review flow, and the static frontend export are all sound.
The problems are concentrated at the **seams**: one IAM gap that will make two of the five
GitHub Actions workflows fail outright, a fully orphaned legacy pipeline that still gets baked
into the production analysis image, and dependency/test drift between local dev and what
actually ships to Lambda.

---

## 1. Blocking issues (fix before the next staging deploy)

### 1.1 Missing `ecr:DescribeImages` IAM permission breaks two workflows

`infra/github-oidc.yaml:241-253` grants `GitHubDeploymentRole` only:

```yaml
- Sid: PushApplicationImages
  Action: [ecr:BatchCheckLayerAvailability, ecr:CompleteLayerUpload,
            ecr:GetDownloadUrlForLayer, ecr:InitiateLayerUpload,
            ecr:PutImage, ecr:UploadLayerPart]
- Sid: LoginToEcr
  Action: ecr:GetAuthorizationToken
```

There is no `ecr:DescribeImages` grant anywhere in the role. But three workflow steps call
`aws ecr describe-images`:

- `.github/workflows/deploy-staging.yml:83-93` — "Reject an existing immutable release tag"
  (stderr suppressed, so an `AccessDeniedException` is silently swallowed and the check is
  bypassed rather than failing loudly — a false sense of safety).
- `.github/workflows/deploy-staging.yml:140-147` — "Verify all release images exist" (stderr
  **not** suppressed) — this step will fail outright on every run, *after* the images have
  already been built and pushed, wasting the build.
- `.github/workflows/prepare-staging-backend-rollback.yml:54-66` — resolving the previous
  release SHA to roll back to — also fails outright, meaning **the rollback workflow cannot
  function at all** as currently deployed.

**Fix:** add `ecr:DescribeImages` to the `PushApplicationImages` statement (or a new
statement) in `infra/github-oidc.yaml`, scoped to the same three repository ARNs.

### 1.2 Orphaned legacy pipeline is broken *and* still shipped into the production image

There are two independent, divergent implementations of "scrape → parse → categorize →
summarize → store":

- **Live pipeline:** `backend/lambdas/discovery.py` → `download.py` → `analysis.py`, driven by
  SQS, using `app/crud/scrape_run.py` for idempotent state transitions. This is what's wired
  into `infra/template.yaml` and what the design doc describes.
- **Dead pipeline:** `backend/app/services/scraping.py::run_ticker_scrape` →
  `backend/scrapers/registry.py::scrape()` → `backend/parsing/pipeline.py::process_announcement`
  → `backend/parsing/storage.py::store()`. This trio dedupes on a *different* key
  (`content_hash` in `parsing/storage.py:211`, vs. the live pipeline's
  `source_document_identity`), calls Groq/FinBERT synchronously in-process, and contains a
  `time.sleep(3)` rate-limit hack (`parsing/storage.py:161`).

A repo-wide grep confirms **no caller of `run_ticker_scrape` exists anywhere** — not in
`main.py`, not in any router, not in any Lambda. It's fully orphaned. Worse, it's also broken
if anything ever calls it: `parsing/pipeline.py:24-27` does bare imports
(`from categories import ReportCategory`, `from classifier import classify`,
`from storage import store`) that only resolve when the file is run directly as `__main__`
(Python adds the script's own directory to `sys.path`); imported as `parsing.pipeline` from
elsewhere, these imports raise `ImportError`.

Despite being dead, `backend/Dockerfile.analysis:23` does `COPY parsing ${LAMBDA_TASK_ROOT}/parsing`,
copying the **entire** `parsing/` directory — including this broken, unused trio plus
`test_pipeline.py` and `print_artifacts.py` — into the deployed analysis Lambda image, even
though only `parsing/analysis.py` and `parsing/classifier.py` are actually used at runtime.

**Fix:** delete `backend/app/services/scraping.py`, `backend/parsing/pipeline.py`,
`backend/parsing/storage.py`, `backend/parsing/test_pipeline.py`, and
`backend/parsing/print_artifacts.py` (or explicitly confirm they're intentionally retained for
some out-of-band CLI use and exclude them from `Dockerfile.analysis`'s `COPY`). At minimum,
change `Dockerfile.analysis` to copy only the files it needs (`parsing/analysis.py`,
`parsing/classifier.py`, `parsing/categories/`, `parsing/__init__.py`) instead of the whole
directory.

---

## 2. High-severity architectural risks

### 2.1 Four drifting sources of Python dependency truth

The pre-existing monolithic `backend/requirements.txt` (used by `backend/Dockerfile` and every
`docker-compose*.yml`) was left completely untouched by this branch, while the new
Lambda-targeted split (`requirements-runtime.txt` + `requirements-api.txt` /
`requirements-analysis.txt` / `requirements-scraper.txt`) pins substantially different
versions of the same packages:

| Package | `requirements.txt` (local dev) | Split files (Lambda/prod) |
|---|---|---|
| transformers | `4.41.0` | `5.14.1` (**major** bump) |
| pypdf | `4.2.0` | `6.14.2` (**major** bump) |
| torch | `2.3.0` | `2.13.0` |
| fastapi | `0.111.0` | `0.139.2` |
| sqlalchemy | `2.0.30` | `2.0.51` |
| psycopg2-binary | `2.9.9` | `2.9.12` |
| pydantic | `2.7.1` | `2.13.4` |
| playwright | `1.44.0` | `1.61.0` |

Because the *same* shared modules run against both version sets (`app/services/sentiment.py`
against transformers/torch, `parsing/analysis.py` against pypdf, `lambdas/source_download.py`
against Playwright), code that passes locally can behave differently — or break — against what
actually deploys. This is compounded by §2.2 below: there is currently no automated way to
catch that divergence before it reaches staging.

**Fix:** either retire `backend/requirements.txt`/`backend/Dockerfile` in favor of building
local dev containers from the same split files (e.g. `requirements-runtime.txt` +
`requirements-api.txt` + `requirements-analysis.txt` + `requirements-scraper.txt` combined), or
add a CI check that fails when a shared package's pinned version disagrees between the two
sets.

### 2.2 Local dev and CI never exercise the actual Lambda images or the pipeline end-to-end

`docker-compose.yml`, `docker-compose-dev.yml`, and `docker-compose-tests.yml` were essentially
untouched by this branch (only a 2-line DB port change in `docker-compose-dev.yml`). All three
still build from the old monolithic `backend/Dockerfile` and run `main.py` directly via
`uvicorn` — `Dockerfile.api`/`Dockerfile.scraper`/`Dockerfile.analysis` and their
`lambdas.*.handler` entry points are **never built or invoked locally or in
`docker-compose-tests.yml`**; they're only built for the first time inside
`deploy-staging.yml` at actual deploy time.

Locally, the pipeline can't even be exercised end-to-end: `app/services/scrape_queue.py:19-20`
raises `RuntimeError("DISCOVERY_QUEUE_URL is not configured")` if unset, and
`.env.example:22` ships it empty, so `POST /scrape/{ticker}` always 503s locally
(`main.py:219-230`). There's no LocalStack/SQS wiring for local dev.

Additionally, **no CI workflow runs `pytest`/`bandit`/`pylint`/`mypy` at all.**
`backend/pytest.ini`, `backend/bandit.yaml`, and `backend/.pylintrc` are correctly wired into
`backend/tests.sh` and `docker-compose-tests.yml`, but none of the five GitHub Actions
workflows reference `docker-compose-tests.yml` or run tests/lint/security scanning before
`deploy-staging.yml` builds and pushes images straight from source. Given this branch's stated
purpose is to *harden* the deployment pipeline, shipping to staging with zero automated
verification gate is a significant gap.

**Fix:** add a workflow (or a job at the start of `deploy-staging.yml`) that runs
`docker compose -f docker-compose-tests.yml up --abort-on-container-exit` (or equivalent)
before any image build/push step. Separately, consider a `docker-compose.yml` profile that
builds the three Lambda images locally against a LocalStack SQS/S3 stack so the pipeline can be
smoke-tested pre-deploy.

### 2.3 Duplicated upsert logic — one path has a race-condition fix the other lacks

`backend/app/crud/artifact_summary.py:17-52` (`upsert_artifact_summary`) and
`backend/app/crud/artifact_sentiment.py:17-58` (`upsert_artifact_sentiment`) both
query-or-create by `artifact_id`, and on `IntegrityError` from the new
`UniqueConstraint(artifact_id)` (a concurrent-write race), roll back, re-query, and retry the
update. `backend/app/crud/artifact.py:38-98` (`store_artifact_analysis`) — used by
`backend/lambdas/analysis.py:350-352`, i.e. the actual Lambda write path — reimplements the
same query-or-create logic for both tables **without** that retry. A concurrency fix applied to
the API write path was not applied to the Lambda write path that hits the same constraint.
Currently low-probability (`AnalysisFunction` runs at `ReservedConcurrentExecutions: 1`), but a
latent bug if analysis concurrency is ever increased, or if the same artifact is reprocessed
concurrently via a DLQ redrive racing a fresh message.

**Fix:** have `store_artifact_analysis` call `upsert_artifact_summary`/`upsert_artifact_sentiment`
directly instead of duplicating the logic.

### 2.4 Unauthenticated API routes can incur unbounded Groq LLM spend, outside every existing cost control

The repo's AI cost controls (`AnalysisEnabled`, `BedrockEnabled`, and the AWS/Bedrock budgets in
`infra/bootstrap.yaml`) all gate the **asynchronous SQS pipeline** — specifically, disabling
`AnalysisEnabled` only detaches the Analysis Lambda's SQS event source mapping
(`infra/template.yaml:443-449`). They do **not** cover two synchronous FastAPI routes that call
the Groq API directly from the `ApiFunction` Lambda, and neither route requires
authentication:

- `POST /gemini/categorise/recent` (`backend/app/api/routes/gemini.py:27-35`) — accepts
  `limit` (default 200) and `batch_size` query parameters and calls
  `gemini_service.categorise_chunk_in_batches`, which makes one Groq HTTP request per batch.
- `POST /category-sentiment/{ticker}` (`backend/app/api/routes/category_sentiment.py:361-372`)
  — accepts `asx_limit` (default 200), `reddit_limit` (default 50), and `batch_size`, and
  similarly drives Groq calls via `groq_service.categorise_chunk_in_batches`.

Both routes' only dependency is `Depends(get_db)` — grepping both files confirms no
`require_admin_investor`, no session/auth dependency, and no rate limiting beyond the API
Gateway's global, account-wide `ThrottlingBurstLimit: 20` / `ThrottlingRateLimit: 10`
(`infra/template.yaml:224-226`), which bounds request *rate*, not the number of Groq calls a
single request can fan out into via `limit`/`batch_size`. Anyone who can reach
`/api/gemini/categorise/recent` or `/api/category-sentiment/{ticker}` can trigger repeated,
attacker-controllable-volume Groq spend, and — because Groq is billed outside AWS — **none of
the existing budget alarms would catch it**: `deployment.md`'s cost table only defines an AWS
monthly budget and a Bedrock-specific budget; there is no Groq spend alarm anywhere in
`infra/bootstrap.yaml`.

**Fix:** add the same `require_admin_investor` dependency already used on the admin-gated
`/scrape/{ticker}` route (`main.py`) to both of these routes, and consider a
request-level cap on `limit`/`asx_limit`/`reddit_limit`/`batch_size` so a single authenticated
request can't fan out into an unbounded number of Groq calls.

### 2.5 Backend rollback workflow can silently change unrelated feature flags

`.github/workflows/prepare-staging-backend-rollback.yml:92-99` hardcodes
`ScheduleEnabled=false`, `AnalysisEnabled=true`, `BedrockEnabled=false`,
`ScheduledTickers=ANZ,BHP,CBA,CSL,WES` for the rollback change set, rather than reading back the
live stack's current parameter values. If the deployed stack currently differs (e.g. the
schedule was enabled, or `ScheduledTickers` was narrowed after BHP failed its smoke test — see
`deployment.md`'s "Known release gate"), an image rollback silently bundles an unrelated
configuration change into the same change set. Person 1's mandatory review mitigates this, but
a rollback workflow shouldn't have side effects on unrelated configuration by default.

**Fix:** read the current stack's parameter values (e.g. `aws cloudformation describe-stacks`)
and pass them through unchanged, overriding only the three image URI parameters.

---

## 3. Medium-severity findings

### 3.1 Two independently-maintained ticker catalogs
`backend/scrapers/registry.py:11-17` (`REGISTRY`) and `backend/app/sources.py:16-48`
(`SOURCES`) both enumerate the same 5 tickers (ANZ, BHP, CBA, CSL, WES) but are separate
dicts with nothing enforcing they stay in sync. They currently agree, but a future ticker
addition to one and not the other would fail silently rather than raise an import-time error.
Consider deriving `REGISTRY` from `SOURCES` (or vice versa) so there's a single source of truth.

### 3.2 No enum/constraint on pipeline status strings
`scrape_runs.status`, `artifacts.download_status`, and `artifacts.analysis_status` are plain
`String` columns with no DB `CheckConstraint` and no shared Python enum. The literal status
strings (`queued`, `discovering`, `downloading`, `analyzing`, `completed`, `partial`, `failed`,
etc.) are repeated across `crud/scrape_run.py`, `lambdas/discovery.py`, `lambdas/download.py`,
`lambdas/analysis.py`, `main.py`, and tests. A typo in any one of these wouldn't be caught until
runtime. Given how central this state machine is to the whole pipeline's idempotency
guarantees, a shared `enum.StrEnum`/constants module (and ideally a DB check constraint) would
meaningfully reduce risk.

### 3.3 Alembic migration-vs-runtime URL separation is a runbook step, not code
`backend/alembic/env.py:18` sets `sqlalchemy.url` from the same `settings.DATABASE_URL` used
at runtime — there's no distinct migration-URL setting in code. `infra/README.md`'s requirement
to "use a direct or session-pooler connection for Alembic migrations" (as opposed to the
transaction-mode pooler Lambdas use) is honored only because the documented runbook temporarily
overrides the env var (`DATABASE_URL="$MIGRATION_DATABASE_URL" python -m alembic upgrade head`).
Anyone running `alembic upgrade head` without that override would apply DDL through the
transaction-pooler connection, which Supabase's transaction mode may not tolerate well for
schema changes. Consider a dedicated `MIGRATION_DATABASE_URL` fallback directly in `env.py`.

### 3.4 Repeated per-record DB connections in the discovery Lambda
`backend/lambdas/discovery.py`'s `_handle_record` opens a fresh `with database_session()` block
multiple times per invocation (run lookup, per-announcement inside the loop at line ~141,
completion marker) — up to ~6 short-lived connections per single SQS message when
`MAX_DOCUMENTS_PER_RUN=3`. `NullPool` is correctly used under `AWS_LAMBDA_FUNCTION_NAME`
(`app/database/connection.py:24-27`), and reserved concurrency (Discovery=1) keeps this well
within Supabase's pooler limits today, but it adds avoidable per-connection TCP/TLS latency and
is worth consolidating into a single session per invocation if discovery throughput ever needs
to grow.

---

## 4. Configuration hygiene

### 4.1 `.env.example` is missing several variables the code actually reads
`DOWNLOAD_QUEUE_URL` and `RAW_DOCUMENT_BUCKET` are read via bare `os.environ[...]`
(`lambdas/discovery.py:110`, `lambdas/download.py:212`, `lambdas/analysis.py:393`) and will
`KeyError` if unset — undocumented anywhere in `.env.example`. Also undocumented:
`DATABASE_URL_PARAMETER`, `GROQ_API_KEY_PARAMETER`, `MAX_DOCX_UNCOMPRESSED_BYTES`,
`MAX_OCR_PIXELS_PER_PAGE`, `CORS_ORIGINS`, `SESSION_COOKIE_NAME`, `SESSION_EXPIRE_DAYS`,
`SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE`, and `DATABASE_URL` itself (compose files
set it directly, but a bare local run silently falls back to
`postgresql://user:password@localhost:5432/spike`).

### 4.2 Dead settings
`OLLAMA_BASE_URL` and `OLLAMA_MODEL` (`app/core/config.py:94-95`) are declared but never
referenced anywhere else in the codebase — leftover from an integration that was never
finished or was removed. Safe to delete.

### 4.3 `.dockerignore` gaps
`backend/.dockerignore` doesn't exclude `.git`, `tests/`, or `*.md` — `backend/Dockerfile:39`'s
`COPY . .` ships the full test suite and git history into local dev images (bloat, not a secret
leak, since `.env` is already excluded). `frontend/.dockerignore` contains only `.env` — it
doesn't exclude `node_modules` or `.next`, so a local build with those present can copy
host-built native bindings into the container, a classic source of Alpine/musl mismatches.

### 4.4 Unusual dependency pins worth verifying before merge
`requirements-api.txt:4` pins `starlette==1.3.1` (Starlette has historically stayed in the
`0.x` series) and pairs it with `mangum==0.19.0`; `Dockerfile.analysis:14` pins
`opencv-python-headless==5.0.0.93` (OpenCV Python wheels have tracked the `4.x` line). If either
version doesn't actually exist on PyPI, `deploy-staging.yml`'s image build fails at
`pip install` time. Worth a quick `pip index versions` check before merge.

### 4.5 Minor redundancy
- `main.py:240-242` defines an explicit `@app.get("/tickers")` that duplicates the same handler
  already mounted via `app.include_router(ticker.router)` at `/tickers/` — harmless, but
  confusing route surface.
- `backend/parsing/env.py` duplicates the `.env`-loading logic already in
  `app/core/config.py`'s `_load_local_env` — small legacy duplication, unused by the live
  pipeline but worth removing alongside §1.2.
- `backend/app/crud/artifact.py:129` — `query.filter(Artifact.ticker_id == ticker.id if ticker else False)`
  is a Python-level ternary evaluated before `.filter()`, passing a raw Python `False` literal
  into SQLAlchemy when `ticker` is `None`. Works via type coercion in modern SQLAlchemy but is
  non-idiomatic; clearer as `Artifact.ticker_id == (ticker.id if ticker else None)`.
- `backend/app/crud/README.md` documents `artifact.py`, `announcement.py`,
  `artifact_summary.py`/`artifact_sentiment.py`, `watchlist.py`, `investor.py`, but never
  mentions `scrape_run.py` — despite it being the largest and most architecturally central
  module in the folder (455 new lines implementing the whole pipeline state machine).
- `backend/app/services/groq.py` is not a real implementation — it's a 9-line re-export shim
  (`from app.services.gemini import (...)`) pointing at `backend/app/services/gemini.py`, where
  every actual Groq HTTP call lives. This is leftover from an earlier Gemini→Groq provider
  swap: `parsing/analysis.py:357` and `app/api/routes/category_sentiment.py:12` import via the
  `groq` alias, while `app/api/routes/gemini.py:11` and the orphaned `parsing/storage.py:22`
  (see §1.2) import the real module directly under its old name. Same code, two module names —
  confusing for anyone tracing "how does Groq get called," and worth collapsing to one name
  (rename `gemini.py` → `groq.py` and delete the shim, updating the handful of import sites).
- The optional-Groq degradation path relies on string-matching an exception message rather than
  a dedicated exception type: `parsing/analysis.py:371-373` does
  `except RuntimeError as exc: if "not configured" not in str(exc).lower(): raise`, keyed to the
  literal text of `RuntimeError("GROQ_API_KEY is not configured")` raised in
  `app/services/gemini.py:114-115,152-154`. This works today, but it's fragile: renaming that
  message breaks the silent-skip behavior without any type error to catch it, and any other
  `RuntimeError` that happens to contain "not configured" would also be silently swallowed. A
  dedicated `GroqNotConfiguredError` exception class would make this robust to message changes
  and make the intentional degrade-on-missing-key behavior self-documenting at the `except` site.
- `backend/tests.sh` (pre-existing, not introduced by this branch) writes output to
  `folder="/test_output/${date}"` — an **absolute** path at the filesystem root — rather than a
  relative path. This would fail with a permissions error outside a container running as root.
  Not introduced by this branch, but still broken and worth a one-line fix
  (`folder="_test_output/${date}"`, matching the `.gitignore` entry `**/_test_output`).

---

## 5. Design-doc vs. implementation cross-check

These were verified explicitly and **match** the design docs — called out here for completeness
since the task asked for deviations, and finding none is itself useful signal:

- Queue topology, visibility timeouts (30 min discovery/download, 72 min analysis = 6× the
  12-minute Lambda timeout), DLQ `maxReceiveCount: 5`, and retention periods all match
  `deployment.md`'s tables exactly.
- Reserved concurrency (API=2, Discovery=1, Download=2, Analysis=1) matches.
- Cost-control defaults (`MAX_DOCUMENTS_PER_RUN=3`, `DISCOVERY_LOOKBACK_DAYS=30`,
  `MAX_DOCUMENT_BYTES=10MiB`, `MAX_PDF_PAGES=100`, `MAX_OCR_PAGES=5`, `MAX_ANALYSIS_CHARS=50000`)
  all match.
- AWS Budget / Bedrock Budget thresholds (50/80/100% and 10/50/100%, excluding credits/refunds)
  in `infra/bootstrap.yaml` match `deployment.md` exactly.
- `BedrockEnabled`/model/token-limit plumbing exists in the template and IAM policy, but no code
  anywhere calls Bedrock — this is explicitly disclosed in `deployment.md` ("the current release
  still uses local FinBERT") and is not a hidden gap.
- OIDC trust policy is scoped to `repo:<org>/<repo>:environment:staging` (not a wildcard), and
  all five workflows declare `environment: staging` and trigger only on `workflow_dispatch` —
  matches the two-person manual-approval design with no auto-deploy-on-push risk.
- Change-set image tags use the full 40-character git SHA consistently end-to-end (build → push
  → change set → deploy → rollback reference) — no `:latest` or short-SHA drift found.
- The database refactor (10-table schema) is internally consistent: no dangling imports of
  deleted models/schemas/crud modules, migrations match model definitions column-for-column, and
  the `models/README.md`/`crud/README.md`/`routes/README.md` docs were correctly updated to
  describe only the surviving tables.
- Frontend static export (`next.config.js`'s conditional `output: "export"`,
  `generateStaticParams` hardcoded to the 5 supported tickers, `trailingSlash: true` compatible
  with the CloudFront Function's URI-rewrite logic, all data-fetching moved to client components
  so no build-time `fetch()` against a relative URL) is correctly implemented and matches the
  "no Next.js server, same-origin `/api/*` via CloudFront" design.

---

## 6. Priority summary

| # | Finding | Severity | Effort |
|---|---|---|---|
| 1.1 | Missing `ecr:DescribeImages` breaks prepare-release & rollback workflows | **Blocker** | Small |
| 1.2 | Orphaned/broken legacy pipeline shipped into analysis image | **High** | Small–Medium |
| 2.1 | 4 drifting dependency sources (local dev vs. Lambda images) | High | Medium |
| 2.2 | No CI test/lint gate; local dev never exercises Lambda images | High | Medium |
| 2.3 | Race-unsafe upsert in Lambda write path | Medium | Small |
| 2.4 | Unauthenticated routes can incur unbounded Groq spend, uncovered by any budget alarm | **High** | Small |
| 2.5 | Rollback workflow can change unrelated feature flags | Medium | Small |
| 3.1 | Duplicate ticker catalogs (`registry.py` vs `sources.py`) | Medium | Small |
| 3.2 | No enum/constraint on pipeline status strings | Medium | Medium |
| 3.3 | Migration DB URL separation is runbook-only | Low–Medium | Small |
| 3.4 | Repeated per-record DB connections in discovery Lambda | Low | Small |
| 4.1–4.5 | Config/documentation hygiene (see above) | Low | Small |

**Recommended order of work:** fix 1.1 immediately (it blocks the deployment process itself),
then 2.4 (an unauthenticated, unbudgeted route to external LLM spend is a real cost/security
exposure, and the fix is a one-line `Depends(require_admin_investor)` addition), then 1.2 (dead
code shipping into prod is a quick, low-risk cleanup), then decide on an approach for 2.1/2.2
together since they're the same underlying gap (local dev doesn't mirror production). The rest
can be picked up incrementally.
