# Developer Experience Recommendations

This is distinct from `recommendations.md` (deployment/architecture/security findings) and
`devops-processes.md` (CI/CD process design). This document is about day-to-day friction for
someone actively writing code in this repo — onboarding speed, local iteration loop, and things
that make it easy to introduce a bug without noticing.

---

## Top 4 — biggest wins for the least effort

### 1. Local dev cannot exercise the actual pipeline at all

`docker-compose.yml`/`docker-compose-dev.yml` build and run `main.py` directly via `uvicorn` —
they never build or run `Dockerfile.api`/`Dockerfile.scraper`/`Dockerfile.analysis` or their
`lambdas.*.handler` entry points. Worse, `app/services/scrape_queue.py:19-20` raises
`RuntimeError("DISCOVERY_QUEUE_URL is not configured")` if that env var isn't set, and
`.env.example` ships it empty — so `POST /scrape/{ticker}` always returns 503 locally. A
developer working on discovery/download/analysis logic currently has **no way to run the
pipeline end-to-end without deploying to AWS staging**, which is slow and shared infrastructure
to iterate against.

**Recommendation:** add a `localstack` service to `docker-compose-dev.yml` (or a
`docker-compose-pipeline.yml` overlay) that stands up SQS queues and an S3 bucket, points
`DISCOVERY_QUEUE_URL`/`DOWNLOAD_QUEUE_URL`/`RAW_DOCUMENT_BUCKET` at it, and runs
`lambdas/discovery.py`, `download.py`, `analysis.py` as long-lived polling processes (or behind
a tiny local SQS-consumer shim) instead of one-shot Lambda invocations. Even a partial version
of this (just discovery → download, skipping the heavier analysis image) would let most
day-to-day pipeline work happen without a staging deploy.

### 2. Nothing runs automatically on a PR

`backend/tests.sh` already wires together `pylint`, `mypy`, `pytest`+`coverage`, and `bandit`
(via `docker-compose-tests.yml`), but none of the five GitHub Actions workflows run it — a
developer only gets this feedback if they remember to run
`docker compose -f docker-compose-tests.yml up` themselves before opening a PR. Frontend has no
CI check at all (no lint/build verification on PRs).

**Recommendation:** add a `ci.yml` workflow triggered on `pull_request` that runs
`docker-compose-tests.yml` for the backend and `npm run build`/`npm run lint` for the frontend.
This is almost pure upside — the tooling already exists, it just needs a trigger. It also
directly catches the dependency-drift problem below before it reaches a reviewer.

### 3. Local requirements vs. deployed requirements have quietly diverged

`backend/requirements.txt` (what `docker-compose*.yml` installs) pins meaningfully older
versions than the split `requirements-api/analysis/scraper/runtime.txt` files that actually ship
to Lambda — e.g. `transformers==4.41.0` locally vs `5.14.1` in the analysis image, `pypdf==4.2.0`
vs `6.14.2`. Since the same modules (`app/services/sentiment.py`, `parsing/analysis.py`,
`lambdas/source_download.py`) run against both, this is a real "works on my machine, breaks in
staging" trap — a developer can write and test code locally that silently behaves differently
once deployed, and won't find out until a staging smoke test fails.

**Recommendation:** either point local dev at the same split-requirements files (compose install
`requirements-runtime.txt` + `requirements-api.txt` + `requirements-analysis.txt` +
`requirements-scraper.txt` together), or add a cheap CI check that fails if a package pinned in
both `requirements.txt` and a split file disagrees on version.

### 4. `.env.example` doesn't actually cover what you need to run features locally

Several env vars the code reads have no entry in `.env.example`: `DOWNLOAD_QUEUE_URL`,
`RAW_DOCUMENT_BUCKET`, `MAX_DOCX_UNCOMPRESSED_BYTES`, `MAX_OCR_PIXELS_PER_PAGE`,
`CORS_ORIGINS`, `SESSION_COOKIE_NAME`/`SESSION_EXPIRE_DAYS`/`SESSION_COOKIE_SECURE`/
`SESSION_COOKIE_SAMESITE`, and `DATABASE_URL` itself (compose sets it directly, so a bare local
run silently falls back to a hardcoded `localhost` connection string instead of failing loudly).
A new contributor copying `.env.example` will hit confusing `KeyError`s or silent wrong-default
behavior rather than a clear "you're missing X" message.

**Recommendation:** add every env var the code actually reads to `.env.example` with a comment
on whether it's required, optional, or Lambda-only (not needed locally).

---

## Onboarding friction

- **Two files named `config.py` doing unrelated things.** `backend/config.py` is a 4-line
  `OUTPUT_DIR` constant used only by the standalone `test_scrapers.py` CLI script.
  `backend/app/core/config.py` is the real `Settings` class the whole app uses. Nothing stops a
  new contributor from editing the wrong one. Rename `backend/config.py` to something specific
  like `backend/cli_config.py`, or fold its one constant into the script that uses it.
- **`app/services/groq.py` is a 9-line re-export shim** of `app/services/gemini.py`, where all
  the real Groq-calling code actually lives — a leftover from an earlier Gemini→Groq provider
  swap. Anyone tracing "how does the LLM summary get generated" hits two files with the same
  logic under different names. Rename `gemini.py` → `groq.py`, delete the shim, update the four
  import sites.
- **An entire orphaned legacy pipeline is still in the tree and still gets built into the
  analysis Docker image.** `app/services/scraping.py`, `parsing/pipeline.py`, and
  `parsing/storage.py` implement a second, older scrape→analyse→store flow with no callers
  anywhere in the codebase — and `parsing/pipeline.py`'s imports are actually broken if anything
  ever calls it (they only resolve when run as `__main__`). A new contributor grepping for
  "where does analysis happen" will find two candidates and have no signal for which one is
  real. Delete these three files (see `recommendations.md` §1.2 for the full detail).
- **`crud/README.md` doesn't document `scrape_run.py`**, despite it being the largest and most
  architecturally central module in the folder (the whole pipeline state machine — 455 lines).
  Someone trying to understand how idempotency/status transitions work has to read the code
  cold instead of getting a README pointer to start from.
- **No documented local Python version or single install command.** Backend dependencies are
  split across five `requirements-*.txt` files plus `requirements-testing.txt`; there's no
  `.python-version` file and no README section saying "here's how to set up a local venv outside
  Docker for fast iteration/debugging." Anyone who prefers running the backend directly (e.g. for
  a debugger, rather than through Docker) has to reverse-engineer which files to install and
  which Python version the Lambda images actually use (3.11 for API, 3.12 for analysis).

---

## Small code changes that remove ongoing footguns

- **No shared enum for pipeline status strings.** `scrape_runs.status` and
  `artifacts.download_status`/`analysis_status` are plain strings, and the literal values
  (`"queued"`, `"discovering"`, `"downloading"`, `"analyzing"`, `"completed"`, `"partial"`,
  `"failed"`, etc.) are retyped across `crud/scrape_run.py`, every `lambdas/*.py` file, `main.py`,
  and the tests. A typo compiles fine and fails silently at runtime. A shared
  `class ScrapeRunStatus(StrEnum)` (and equivalents for the artifact sub-statuses) gets you
  autocomplete and a real error at the call site instead of a state machine that quietly gets
  stuck.
- **Duplicated upsert logic across three files** — `crud/artifact_summary.py`,
  `crud/artifact_sentiment.py`, and `crud/artifact.py`'s `store_artifact_analysis` all
  reimplement "query-or-create the one row for this artifact_id" independently (and one of the
  three is missing the retry-on-race fix the other two have — see `recommendations.md` §2.3).
  Beyond the correctness bug, this means a future change to that logic has to be remembered and
  applied in three places instead of one.
- **Two independently-maintained ticker catalogs.** `scrapers/registry.py`'s `REGISTRY` and
  `app/sources.py`'s `SOURCES` both list the same five tickers with nothing enforcing they stay
  in sync. Adding a sixth ticker means remembering to touch both files — an easy thing to miss,
  with no import-time error if you do. Derive one from the other.
- **`backend/tests.sh` writes output to an absolute path**, `folder="/test_output/${date}"`
  (note: no leading `_` either, so it also doesn't match the `.gitignore` entry
  `**/_test_output`). This fails with a permissions error for anyone not running as root inside
  the test container. One-line fix: `folder="_test_output/${date}"`.
- **`backend/.dockerignore` doesn't exclude `.git`, `tests/`, or `*.md`**, and
  `frontend/.dockerignore` only excludes `.env` (not `node_modules`/`.next`) — both make local
  `docker compose build` slower than necessary by shipping unnecessary content into the build
  context on every rebuild, and the frontend gap risks a stale host `node_modules` overwriting
  the container's own install.

---

## Frontend-specific

`docker-compose.yml` builds the `production` Docker target (which runs `npm run build`,
producing the static `out/` export that actually ships to CloudFront) but then overrides the
container's command to `npm run dev` — so local `docker compose up` never exercises the
static-export code path a frontend change actually needs to survive. A change that works fine
under `next dev` (e.g. something relying on a Next.js server feature not supported in static
export) can pass every local check and only break once it's built for deployment.

**Recommendation:** add an `npm run preview` script (`next build && npx serve out`, or similar)
and mention it in the README, so switching from "dev mode" to "what actually ships" is a single
documented command instead of something only the deploy workflow does.

---

## Summary

| Change | Effort | Payoff |
|---|---|---|
| Wire existing `tests.sh`/`docker-compose-tests.yml` into a PR-triggered CI workflow | Small | High — immediate, on every PR |
| Fill in missing `.env.example` variables | Small | High — removes a recurring onboarding stumble |
| Fix `tests.sh`'s absolute output path | Trivial | Medium |
| Reconcile local vs. Lambda dependency versions | Medium | High — closes a "works locally, breaks in staging" gap |
| Delete the orphaned legacy pipeline (`scraping.py`/`pipeline.py`/`storage.py`) | Small | Medium — removes a source of "which one is real" confusion |
| Rename `config.py`/`gemini.py`↔`groq.py` to remove naming collisions | Small | Medium |
| Add a shared status enum for the pipeline state machine | Medium | Medium — prevents a class of silent bugs |
| Local pipeline dev loop (LocalStack SQS/S3) | Larger | High — this is the single biggest iteration-speed unlock |
| Frontend static-export local preview script | Trivial | Medium |
