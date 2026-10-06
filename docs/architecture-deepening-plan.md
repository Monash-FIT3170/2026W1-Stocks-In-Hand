# Architecture Deepening Plan

## In short

- This plan makes the parts of the code that change most often easier to change and easier to test. Those parts are the announcement pipeline, LLM analysis and summaries, the ticker API, investor alerts and deployment.
- The main idea is to take knowledge that is copied across many files and give it one home (a "module") with a small, clear interface. Tests then check that interface instead of private functions.
- The work is split into 18 pieces of work called candidates, grouped into phases. Phase 0 fixes live bugs and deletes dead code first, so the later work starts from a smaller and correct codebase.
- Phase 0 is written and in review as PRs #57 to #65.
- Phase 1 (candidates 01, 15 and 11) is done in this PR, #56. It is built on the Phase 0 branches, which are merged into it, so #56 also shows the Phase 0 changes until #57 to #65 land on `main`. Merge #57 to #65 first so each keeps its own review.
- Some choices belong to the team, not the engineer doing the work. They are listed under [Decisions still needed](#decisions-still-needed).

## What done looks like

1. Every Phase 0 bug is fixed and has a regression test.
2. Adding an ASX ticker means one catalogue entry and one source adapter, not about 20 files.
3. A temporary failure in any pipeline stage never records a final "failed" state before SQS has given up on the message.
4. The summary shape, the FinBERT input and the LLM provider behaviour are each defined in one module.
5. Route files only translate HTTP requests into read-model calls. Who may call a route is set once per router and checked by one sweep test.
6. Alert decisions, email provider errors and the subscription lifecycle each live in one module. Each is tested end to end against Postgres with a fake email sender.
7. Deploy and rollback work out their parameters from one release module. Template tests check rules ("every queue has a dead-letter queue") instead of exact text.
8. Tests call each module through its interface. Tests that patch private functions or check call order are deleted as each candidate replaces them.

## Status at a glance

| # | Candidate | Phase or track | Strength | Size | Depends on | Status |
|---|---|---|---|---|---|---|
| 0 | Bug fixes and dead code | Phase 0 | Must do | L | none | In review (PRs #57 to #65) |
| 01 | Ticker catalogue | Phase 1 | Strong | M | Phase 0 | Done in #56 |
| 15 | Template model | Phase 1 | Strong | M | Phase 0 | Done in #56 |
| 11 | Access policy | Phase 1 | Strong (security) | S | Phase 0 | Done in #56 |
| 04 | Scrape run lifecycle | Phase 2 | Strong | M | 01 | Partly done in Phase 0 |
| 03 | Raw document store | Phase 2 | Strong | M | 01 | Partly done in Phase 0 |
| 02 | Source adapter per company | Phase 2 | Strong | L | 01 | Partly done in Phase 0 |
| 05 | Public discussion collector | Phase 2 | Strong | M | 01 | Not started |
| 06 | Structured generation | Phase 3 | Strong | M | Phase 0 | Partly done in Phase 0 |
| 07 | Artifact summary | Phase 3 | Strong | M to L | 06, citation branches merged | Partly done in Phase 0 |
| 09 | Category taxonomy ownership | Phase 3 | Worth exploring | S to M | Phase 0 | Not started |
| 08 | Artifact analysis | Phase 3 | Strong | L | 03, 04, 06, 07 | Partly done in Phase 0 |
| 10 | Ticker read-models | Phase 4 | Strong (bucket remap: worth exploring) | M | 01, 07, 09, citation branches merged | Partly done in Phase 0 |
| 13 | Email sender port | Alerts track | Strong | S to M | Phase 0 | Partly done in Phase 0 |
| 12 | Alert delivery | Alerts track | Strong | M | 13 | Partly done in Phase 0 |
| 14 | Alert subscription lifecycle | Alerts track | Worth exploring | M | 13 | Not started |
| 16 | Release parameters | Deploy track | Strong | M | 15 | Partly done in Phase 0 |
| 17 | Runtime configuration | Deploy track | Worth exploring | M to L | 15 | Partly done in Phase 0 |
| 18 | OIDC role pair | Deploy track | Speculative | S to M | 16 | Not started |

"Strong" means the problem is clear and the fix is worth doing. "Worth exploring" means it is probably worth doing but needs a closer look or a team decision first. "Speculative" means it may not be needed at all.

The alerts track and the deploy track do not depend on the ingestion or analysis phases. A second person can work on them in parallel once Phase 0 has merged.

## Order of work

1. Merge the Phase 0 PRs #57 to #65. They were trial-merged together with no conflicts, and the combined result passed 639 backend tests.
2. Merge #56, which holds this plan and Phase 1 (candidates 01, 15 and 11). With Phase 0 merged it passes 685 backend tests.
3. Merge the two citation branches that are still open, `feature/86d2ba6e6-claim_source_traceability` and `feature/86d4a0a1d-specific_report_sources`. Both touch `backend/app/api/routes/ticker.py` and `CitationLinks.jsx`, so candidates 07 and 10 will conflict with them if they are not merged first.
4. After that, follow the "Depends on" column. Phase 2 before Phase 3 before Phase 4, with the alerts and deploy tracks in parallel.

## How to work on a candidate

These rules apply to every candidate.

1. Write the tests first, against the new interface. They should pass against today's code, or fail only because of a known bug.
2. Move code behind the new interface in small PRs that keep all tests passing. Switch callers over one at a time. One numbered step is roughly one PR unless the step says otherwise.
3. Replace old tests instead of keeping both. Once tests at the new interface cover a module, delete that module's old tests, especially ones that patch private functions or check call order.
4. Name the module. Add each new module's name and a one-line meaning to `CONTEXT.md` in the repo root (create the file when the first name is added). If the team decides not to do a candidate, and future reviewers would need to know why, record it as an ADR in `docs/adr/`.

### Repo rules to follow

- Branch off `main`. The hooks in `.githooks` only allow `feature/<9-character ClickUp id>-<description>`, `bugfix/<description>` or `admin/<description>`. Use underscores, not hyphens, inside the description.
- Commit messages on `feature/` branches look like `3.2.3.86d2buamy - Description`. On `bugfix/` and `admin/` branches they look like `3.2.3 - Description`.
- Run the backend tests from the repo root with `python -m pytest -q backend/tests`. Set `DATABASE_URL` to a Postgres database that has been migrated with `python -m alembic upgrade head` (run from `backend/`). Database tests skip themselves when Postgres is not reachable, so a run with no database can pass without testing much. On Windows, install `tzdata` so `ZoneInfo("Australia/Sydney")` works.
- The "Queue wiring regression tests" CI job installs only pytest and PyYAML, and runs `test_queue_wiring.py` and `test_deployment_contracts.py`. Keep those two files, and anything they import, free of other dependencies. Today that means `backend/app/sources.py`, `backend/tools/sync_tickers.py`, `backend/tools/template_model.py` and `backend/tools/verify_queue_wiring.py`.
- Line references in this plan point at `main` commit `c6e7574`. Phase 0 moves some code, so if a line does not match, search for the function or symbol name instead.
- If several agents work in separate git worktrees at the same time, do not use `git stash`. The stash is shared by every worktree of a repo, so two agents' changes can swap.

## Words used in this plan

Most of the plan uses plain words. These few terms have a specific meaning here.

- Module: anything with an interface and an implementation. It can be a function, a class, a package, or a slice across several layers.
- Interface: everything a caller needs to know to use a module correctly. That includes the types, and also rules about order, error cases and required configuration.
- Deep module: a module that hides a lot of behaviour behind a small interface. A shallow module has an interface almost as complicated as its code. The aim of this plan is to turn shallow modules into deep ones.
- Seam or port: the point where a module's interface sits, where one implementation can be swapped for another without editing the code on either side.
- Adapter: one implementation that plugs into a seam. With one adapter the seam is only on paper. With two (usually the real one and a fake for tests) the seam is real.
- Locality: the knowledge about something, and the bugs and fixes for it, sit in one place instead of being spread across many files.
- Leverage: how much a caller gets out of a module for each thing they have to learn about its interface.
- Deletion test: imagine deleting the module. If its complexity just disappears, it was a pass-through and can go. If the complexity would reappear in several callers, it is doing useful work.

Each candidate also says how its tests should reach outside code:

- Pure code: test it directly.
- Real Postgres or LocalStack: run the real thing in the tests.
- A service we own: put it behind an interface with a real version and an in-memory version for tests.
- A third-party service: put it behind an interface and use a fake in tests.

## Scope and method

- The plan covers the areas that changed most in the 80 commits before `c6e7574`.
- Four reviewers read the code in parallel without changing it. Their findings were combined, and every bug marked "verified" was checked again against the code.
- The classification design is already decided in `docs/advanced-content-classification-implementation-plan.md`. `classify_document` stays the single external seam, with no provider ports. This plan builds on that and does not reopen it.
- The repo had no `CONTEXT.md` and no ADRs when this plan was written. #56 adds `CONTEXT.md` with the first project terms.

## Phase 0: fix live bugs and delete dead code

Status: written and in review. Nothing here needs to be done again. This section records what each PR changed and what was left over.

### Bugs fixed

| Bug | PR | What changed |
|---|---|---|
| Ten write routes needed no login. The three `/news` POST routes spend Marketaux and Bedrock credits, an anonymous `POST /artifact-sentiments/` could change a ticker's "latest signal", and `PATCH /tickers/{id}` called `setattr` on any field. | #57 | All ten routes need an admin session. The two PATCH routes take `TickerUpdate` and `InformationPlatformUpdate` schemas. `test_access_policy.py` fails for any write route without a login check unless it is on a short public allowlist. |
| With Bedrock disabled, every analysis failed and retried. The fallback looked for the text "not configured", which only Groq raised. | #58 | Both providers raise `LLMUnavailableError` (`app/services/llm_errors.py`), and analysis stores sentiment without a summary when it sees it. |
| The admin summary routes could truncate, because ApiFunction allowed 1024 output tokens and AnalysisFunction allowed 4096. | #58 | ApiFunction now allows 4096. |
| The rollback workflow hard-coded `AuthProvider=legacy` and every feature switch, and had no image mapping for NotificationFunction. A rollback would have switched a Cognito stack back to legacy login and turned off schedules, Marketaux and Bedrock. | #59 | The rollback reads the live stack's parameters and changes only the three image URIs. |
| Alert and verification emails linked to the CloudFront domain instead of the custom domain. | #59 | Deploy sets `FrontendBaseUrl` to `https://$SITE_DOMAIN_NAME` when that variable is set. |
| Two template tests still passed when the `NotificationsEnabled` or `PublicDiscussionScheduleEnabled` default was flipped to `"true"`. | #59 | They read the parsed template now. `backend/tests/cloudformation_template.py` holds the shared loader. |
| Neutral-only alert rules never fired. The UI, schema and rule validation accepted "neutral" but the producer dropped it. | #60 | `app/alert_vocabulary.py` defines the alert labels once. Neutral works end to end. |
| A temporary failure marked an artifact or run as failed, and the retry then undid it. The API and scheduler could also enqueue a second Queue A message during a retry. | #61 | Retryable errors record the error only. The final state is recorded on the last receive (`MAX_RECEIVE_COUNT = 5` in `lambdas/common.py`). `test_transient_failures.py` reproduces the duplicate enqueue on `main`. |
| Category sentiment gave rows with 0 or NULL confidence the most weight (`confidence or 1.0`). | #62 | Confidence is the weight. If no row has any confidence, labels are counted equally. |
| Appendix 3G/3H notices counted as "risk", because "securitynotification" contains "security". | #62 | Keywords match whole words only. Whether one artifact can count in several buckets is still open (see decisions). |
| The document size limit was 10 MiB in code and 25 MiB in the template. The DOCX limit was 50 MiB in code and 20 MiB in the template. | #62 | Both defaults live in `lambdas/download_validation.py` (`document_size_limit()`, `docx_uncompressed_limit()`) and match the template. |
| The unsubscribe header invited a one-click POST, but CloudFront only allows GET on that page. | #62 | The `List-Unsubscribe-Post` header and the `ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED` flag are removed. The flag was off everywhere, so no sent email had the header. |
| The news summary route inserted a new summary row, which hit the unique constraint when a summary already existed. The local loader did the same. | #62 | Both use `upsert_artifact_summary`. |
| FinBERT scored three different texts depending on the path. The local loader scored the LLM summary. | #62 | `sentiment.sentiment_input(title, raw_text)` is the one input, capped at `MAX_ANALYSIS_CHARS`. This matches what the production worker already did. |
| `/news-feed`, `/sentiment/{t}` and the public-discussion status route returned 404 on a fresh database until another route had created the ticker rows. | #62 | Migration `86d9seedtickers` seeds the 13 tickers. It keeps curated values and is safe to run twice. |

### Dead code deleted

| Deleted | PR |
|---|---|
| `_download_via_browser` in 8 scrapers (about 200 lines). | #63 |
| `download.SUPPORTED_ADAPTERS`. `QueueBMessage.adapter_must_match_ticker` already does this check. | #63 |
| The `download_pdf` and `DownloadedPdf` shims, and the unused `final_url` parameter of `validate_document_content`. | #63 |
| `backend/app/services/scraping.py`, nine dead helpers in `category_sentiment.py`, and `sentiment.analyse_categories`. | #64 |
| The `app/services/gemini.py` and `groq.py` re-export shims. | #64 |
| The `/tickers/symbol/{s}/overview` and `/brief-aside` routes and their unused frontend fetch functions. `/brief` stays. | #64 |
| `_is_bluesky_ticker_post` and `_is_mastodon_ticker_post` and their tests. | #64 |
| 15 unread `Settings` fields (14 in #65, `NOTIFICATION_QUEUE_URL` in #62), the stale `GROQ_API_KEY_PARAMETER` in `.env.example`, `SEED_TICKERS` in both compose files, and the `enqueue_public_discussion_analysis` alias. | #65, #62 |

### Left over from Phase 0

These were found or deferred during Phase 0. Each one is also noted in the candidate it belongs to.

- `"tone": "green"` in the deep-dive timeline is not dead. `frontend/src/app/components/ticker/DeepDiveTimeline.jsx` uses it as the CSS class that colours the timeline dot. To remove it, hard-code `styles.green` in the component first (candidate 10).
- `BaseScraper.download_pdf` is still used by `backend/scripts/populate_local_content.py` and still imports `lambdas.source_download` (candidate 02).
- `crud.artifact.get_bluesky_posts_for_ticker` and `get_mastodon_posts_for_ticker` became dead in #64 but were not on the list (candidate 05).
- `/headlines` and `/analyse` in `backend/main.py` were kept because they may still be used locally. `/analyse` now needs an admin session.
- If a Lambda times out on its final receive, its error handler never runs, so nothing records the final failure (candidate 04).
- With 4096 output tokens, an admin summary route could come close to the 30-second API Gateway limit (candidate 06).
- Run "Prepare staging backend rollback" once against staging to check the #59 change. It only creates a change set. The only parameter changes should be the three image URIs (candidate 16).
- Deleting unread `Settings` fields means a malformed `MAX_*` or `DISCOVERY_LOOKBACK_DAYS` value no longer crashes the API at import. The Lambdas that read them still fail on bad input (candidate 17).

## Phase 1: foundations

### 01 Ticker catalogue

Strong, size M. Done in #56. Unblocks 02, 03, 04, 05 and 10. Test approach: pure code.

What was wrong
- The list of supported companies was copied into about 13 places. Commit `9bdc05c` touched 20 files to add eight tickers and still missed the CloudFront route regex, which `8a928c1` then had to fix.
- Five different "get or create ticker" paths wrote different company names, so public-discussion mention matching depended on which route ran first.
- `_ensure_default_tickers` ran up to 13 SELECTs on every read route.

What was built

The ticker catalogue in `backend/app/sources.py`. Each `SourceDefinition` owns one company's facts: symbol, name, sector, industry, source adapter, source URL and whether the weekly schedule includes it by default. Every other list of tickers is generated from it or checked against it.

Done in #56
1. `SourceDefinition` has the company name, sector, industry and a `scheduled` flag. `DEFAULT_TICKERS` is gone from `ticker.py`. The schedule falls back to `scheduled_tickers()` when `SCHEDULED_TICKERS` is unset, instead of every ticker. The seed migration test compares the snapshot's facts, not just the symbols.
2. `normalise_symbol` (strip, upper-case, drop `.AX`) lives in the catalogue. `crud.ticker.ensure_ticker` is the one "make sure the ticker row exists" path: it writes the catalogue's facts, fills placeholders on existing rows, joins the caller's transaction and absorbs a concurrent insert. Scrape runs, Marketaux and the local loader use it, and `get_ticker_by_symbol` and `TickerCreate` normalise the symbol. The admin `POST /tickers` route still creates exactly what it is given.
3. `_ensure_default_tickers` is removed from the read routes. Migration `86d9seedtickers` seeds the rows and deploy runs it.
4. The scraper registry maps adapters to scrapers and takes its ticker keys from the catalogue. The analysis worker builds its `OBJECT_KEY` pattern from the catalogue and checks identity with `adapter_matches_ticker`, so its own `SUPPORTED_TICKERS` set is gone.
5. `backend/tools/sync_tickers.py` rewrites the copies that cannot import Python: `frontend/src/app/ticker/tickers.json` (read by `generateStaticParams`), the CloudFront `tickerRoute` pattern, the `ScheduledTickers` default and both scheduled-ticker defaults in `deploy-staging.yml`. `test_ticker_list_copies_match_the_catalogue` fails when a copy is stale, and the queue-wiring CI job now runs on catalogue changes. The ApiFunction's `SUPPORTED_TICKERS` variable is removed because `Settings` already defaults to the catalogue.
6. The ticker list in `docker-compose-dev.yml` and the ticker and source-URL lines in `backend/.env.example` are removed.

To add an ASX ticker now: add a catalogue entry, add its scraper to `SCRAPERS` in `backend/scrapers/registry.py` and its resolver, write a seed migration for the row, update `test_migration_seeds_the_catalogue_facts` to read it, and run `python -m tools.sync_tickers` in `backend/`.

Tests
- `test_ticker_catalogue.py`: normalisation, and Postgres tests for `ensure_ticker` (seeded row, catalogue facts, a repeat call, unknown symbol, placeholders filled and curated values kept).
- The text search in `test_deployment_contracts.py` is replaced by the sync check, and the AST check in `test_expanded_scraper_registry.py` by catalogue-wide scraper and object-key tests.
- The `_ensure_default_tickers` call-count tests in `test_apis.py` are deleted.

Left over
- `infra/README.md` still shows `export SCHEDULED_TICKERS=ANZ,BHP,CBA,CSL,WES` in an example command. Candidate 16 replaces the README command copies.
- Migration `86d9seedtickers` is a snapshot. A new ticker needs its own seed migration.

Where the code is: `backend/app/sources.py`, `backend/app/crud/ticker.py`, `backend/scrapers/registry.py`, `backend/lambdas/analysis.py`, `backend/lambdas/schedule.py`, `backend/tools/sync_tickers.py`, `frontend/src/app/ticker/tickers.json`.

### 15 Template model

Strong, size M. Done in #56. Unblocks 16 and 17. Test approach: pure code.

What was wrong
- The tests read `infra/template.yaml` in three different ways: 19 text slices that depended on resource order, a regex, and a YAML loader.
- They checked exact values that someone remembered to check, and some could never fail.
- The Notification queue was missing from the queue-wiring checks.
- Nothing stated that a queue's visibility timeout must be at least 6 times its consumer's timeout.

What was built

`backend/tools/template_model.py` parses the template once and answers questions about it: functions, the queue each function consumes, SendMessage targets (including grants under `!If`), environment variables, readable SSM parameter names, queue settings, dead-letter queues, the alarms watching a queue and the outputs that export it. Intrinsic functions keep CloudFormation's JSON form, so `!Ref` and `!GetAtt` can be told apart. It needs only PyYAML.

Done in Phase 0 (#59, #61, #62): the shared loader, the feature-switch, image-mapping, parameter and rollback rules, the `maxReceiveCount` check and the document size check.

Done in #56
1. The template model replaces `backend/tests/cloudformation_template.py`.
2. `test_queue_wiring.py` checks rules against it, and runs each rule against a template broken on purpose (a test fails if a rule has no breakage):
   - Every consumed queue has a dead-letter queue, a DLQ alarm and URL outputs.
   - The visibility timeout is at least 6 times the consumer's timeout.
   - Every `*_QUEUE_URL` variable has a SendMessage grant, and every grant has a `*_QUEUE_URL` variable.
   - Every `*_PARAMETER` variable has an `ssm:GetParameter` grant.
   - Queues are encrypted, dead-letter queues keep messages longer than their sources, and DLQ alarms page the alarm topic.
3. The text-slice checks these replace are deleted, and the remaining template slices in `test_deployment_contracts.py` (notification, Bedrock, Marketaux, Cognito, custom domain, CloudFront, public discussion) read the model. The test that the workflow contains `python -m pytest` is deleted.
4. `backend/tools/verify_queue_wiring.py` replaces the bash arrays in `verify-staging-queue-wiring.yml`. It takes the resources, outputs and queue settings to check from the model, so the notification queue is now checked too. It is tested against a fake deployed stack built from the model.

Left over
- Run "Verify staging queue wiring" once on staging. The script is tested offline only, and the workflow now checks out the repo and installs PyYAML.
- The workflow text checks in `test_deployment_contracts.py` (deploy and rollback workflows) belong to candidate 16, and the `github-oidc.yaml` text checks to candidate 18.

Where the code is: `backend/tools/template_model.py`, `backend/tools/verify_queue_wiring.py`, `backend/tests/test_queue_wiring.py`, `backend/tests/test_template_model.py`, `backend/tests/test_deployment_contracts.py`, `.github/workflows/verify-staging-queue-wiring.yml`.

### 11 Access policy

Strong (security), size S. Done in #57 and #56. Test approach: pure code.

What was wrong

`require_admin_investor` exists to protect cost-bearing routes, but each handler had to remember to use it, and ten did not. The same operation could have different rules: `/gemini/summarise` was admin-only while `/news/summarise` was open. `recommendations.md` §2.4 had already flagged the unbounded LLM spend.

Done in Phase 0 (#57)
- The ten routes need an admin session, and the two PATCH routes take schemas instead of a raw dict.
- `backend/tests/test_access_policy.py` sweeps every route, walking the nested routers FastAPI 0.139 keeps.

Done in #56
1. `main.py` includes every router in one policy group, and the include-level dependency decides access: public read (reads open unless the route asks for a login, every other method needs an admin through `require_admin_for_writes`), investor, admin, and self-managed (`auth` and `notification_preferences`, which choose per route). A write route added to a public-read or admin router is admin-only by default, so the 25 per-handler `_admin` dependencies are removed. No route's access changed.
2. The sweep also fails when a write route is not admin-only and is not on the public or investor-owned allowlists, or when a router is included without a policy. The per-route admin tests in `test_scrape_pipeline_api.py`, `test_public_discussion_contracts.py` and `test_bedrock.py` are folded into it.

Watch out for: a new public write route, such as a real one-click unsubscribe endpoint, must go on `PUBLIC_WRITE_ROUTES` in `test_access_policy.py`, and a new investor-owned write route on `INVESTOR_WRITE_ROUTES`. A new router must join a group in `main.py`.

Where the code is: `backend/main.py`, `backend/app/api/deps.py` (`require_admin_for_writes`), `backend/tests/test_access_policy.py`.

## Phase 2: ingestion

### 04 Scrape run lifecycle

Strong, size M. Needs 01. Unblocks 08. Test approach: a service we own (real Postgres plus a fake queue sender).

What is wrong
- Each of the three workers repeats the same steps for every message: decode it, decide whether the error is permanent or retryable, record the outcome and log it.
- "Request a scrape run" is copied in the API (`main.py`) and the scheduler (`schedule.py`), and the copies already disagree. Only the API honours the `{TICKER}_SOURCE_URL` override. The discovery worker ignores `source_url`, while the download worker uses it.

What to build

One scrape run lifecycle module that owns two things. The first is "request a run", with the queue sender passed in. The second is "record a stage outcome": a permanent failure is final, a retryable failure records the attempt only, and the final receive is final.

Done in Phase 0 (#61)
- Retryable failures record the error only, through `record_run_discovery_retry`, `record_artifact_download_retry` and `record_artifact_analysis_retry`. The final receive (`MAX_RECEIVE_COUNT` in `lambdas/common.py`) or a permanent error calls the `mark_*_failed` transition.
- `test_transient_failures.py` drives the real handlers against Postgres, covering the retry cases and the duplicate enqueue.

Steps still to do
1. Pull "request a scrape run" out of `main.py` and `schedule.py` into the module, taking the source from 01. The team decides whether `source_url` is authoritative first (see decisions).
2. Pull the shared stage skeleton out of the discovery, download and analysis workers. The `_mark_failed` and `_record_retry` pairs in each worker are the obvious duplication.
3. Move raw status strings such as `"running"` into `ScrapeRunStatus`, and add a database CHECK constraint (`recommendations.md` §3.2).
4. Remove the `"csl"` defaults from `QueueAMessage`, `QueueBMessage` and `get_or_create_artifact`.

Tests
- Replace about 60 string-path monkeypatches in `test_document_workers.py:331-573` and about 7 MagicMock request tests with scenarios on Postgres and a fake sender.
- Keep the real-Postgres state-machine tests in `test_database.py:966-1125`.

Watch out for
- `items_failed` feeds the run status and maybe the UI, so check its readers first.
- The notify worker uses a different pattern (batch item failures) and is out of scope.
- If a Lambda times out on its final receive, the error handler never runs, so the run is never marked failed. Consider a small DLQ handler or a sweeper for stuck runs.

Where the code is: `backend/lambdas/discovery.py:28-238`, `backend/lambdas/download.py:46-285`, `backend/lambdas/analysis.py:518-863`, `backend/lambdas/common.py:19-68`, `backend/app/crud/scrape_run.py:197-493`, `backend/main.py:199-266`, `backend/lambdas/schedule.py:102-148`, `backend/app/services/scrape_queue.py`, `backend/app/messages.py:59,95`.

### 03 Raw document store and validated document

Strong, size M. Needs 01. Unblocks 08. Test approach: real LocalStack, plus an in-memory store for worker tests.

What is wrong
- The S3 key is split between two workers. The download worker writes `raw/{ticker}/{artifact_id}/{sha256}.{ext}`. The analysis worker reads it back with its own regex (#56 builds its ticker list from the catalogue).
- Both workers mark the artifact as stored.
- A `DownloadedDocument` does not prove it was validated, so it is validated again at four points.
- `document_too_large` is raised in 7 places.

What to build

Make the validation function the only way to create a `DownloadedDocument`. A raw document store module owns, for both workers, the key layout and parsing, object metadata, "put only if absent", "read and verify", and the check that "this object is the stored artifact".

Done in Phase 0
- The size limits agree with the template and live in `lambdas/download_validation.py` (#62).
- The `DownloadedPdf` alias, the `download_pdf` shim and the unused `final_url` parameter are gone (#63).

Steps still to do
1. Make validation the only path that builds a `DownloadedDocument`, then remove the later re-checks one at a time.
2. Move key building and parsing, the metadata headers, "put only if absent" and "read and verify" into the store. The ticker pattern already comes from the catalogue (`OBJECT_KEY` in `lambdas/analysis.py`).
3. Move the reconciliation for "the S3 event arrived before the database commit" (around `analysis.py:217-265`) into the store.
4. Merge the HTTP status classification that is duplicated in `download_validation.py:293-306` and `source_download.py:98-110`.

Tests
- Use an in-memory store for worker tests, plus one LocalStack integration test. The LocalStack compose file already exists. moto is not installed.
- Delete the literal key-string assertions in three test files.
- Keep the `httpx.MockTransport` download tests.

Watch out for
- The key format is also the S3 to SQS notification filter (the `raw/` prefix), so it must stay exactly the same.
- Keep the existing error codes.

Where the code is: `backend/lambdas/download.py:110-244`, `backend/lambdas/analysis.py:70-160,217-318`, `backend/lambdas/download_validation.py:55-376`, `backend/lambdas/source_download.py:113-136`.

### 02 Source adapter per company

Strong, size L (the largest candidate). Needs 01. Test approach: a third-party service (13 real adapters plus recorded page fixtures).

What is wrong
- Each company's knowledge is split in two. The discovery scraper writes hints into an untyped `Announcement.metadata` dict, and the download resolver reads them back. Nothing ties the two sides together. The WDS bug fixed in `33e0889` lived in that gap.
- Constants such as the TCL `APP_ID`, the WES row selector and the YourIR app IDs are copied on both sides.
- 11 of the 13 scrapers have no offline tests.
- A page that fails to load returns `[]`, so a broken site looks like "no new announcements" and the run finishes with 0 items.

What to build

One source adapter per company that owns "list recent documents" and "fetch one document", plus its allowed hosts, referer rules and resolution hints. The page fetcher is passed in, so tests can replace Playwright with recorded pages. With 13 adapters the seam is real.

Done in Phase 0: `_download_via_browser` is deleted from all 8 scrapers (#63).

Steps still to do
1. Move the dev loader (`backend/scripts/populate_local_content.py`) off `BaseScraper.download_pdf`, then delete that method. This also removes the `scrapers` to `lambdas` import, because `BaseScraper.download_pdf` calls `lambdas.source_download.resolve_session_download`.
2. Wrap each existing scraper and resolver pair behind the source adapter interface, using a compatibility registry. No behaviour change.
3. Move the YourIR family first (ANZ, CBA and TCL share feed code). Move `_ADAPTER_HOSTS`, the referer rules and the app IDs into each adapter.
4. Split each adapter into a thin fetch step and a pure parse step. Record one live capture per site as a fixture.
5. Raise "source unreachable" or "layout changed" errors instead of returning `[]`.
6. Pull out shared helpers for each family of sites: listing to article to PDF (BHP, RIO, WDS, ORG, MQG), IRM iframe feeds (COH, TLS), and the dedupe and date helpers, which are currently copied 9, 5, 5 and 4 times.

Tests
- Add fixture tests for each adapter through "list" and "fetch".
- Delete the tests that reach into `_validated_url`, `_ADAPTER_HOSTS` and `_request_referer`.
- Delete the AST and source-scanning convention tests.

Watch out for: keep Queue B's `metadata` field as the carrier on the wire, so the message schema does not change.

Where the code is: `backend/scrapers/companies/*.py` (13 files), `backend/scrapers/base.py:7-85`, `backend/lambdas/source_download.py:32-477`, `backend/tests/test_source_adapters.py`, `backend/tests/test_scraper_browser.py`.

### 05 Public discussion collector

Strong, size M. Needs 01. Test approach: a third-party service (4 real adapters plus fakes).

What is wrong
- Four route modules copy the same code: platform get-or-create, content hashing, the store loop, the run lifecycle and the enqueue step.
- The copies have drifted. Malformed posts count as duplicates for Bluesky and Mastodon but as failures for blogs, so the `partial` run status can only happen for blogs. A Bluesky post with an empty timestamp aborts the whole batch.
- `PublicDiscussionAdapter` has no real implementations, and the scheduler imports eight private route functions and skips target validation.

What to build

Four thin source adapters at a real seam. Each one fetches, normalises, validates its target, works out identity and works out engagement. One collector module owns everything else: dedup, ticker linking, queueing for analysis, failure counting and the run lifecycle. The routes and the scheduler both call the same `collect`.

Steps
1. Write characterisation tests on Postgres that pin the content-hash formats: `reddit:{id}`, `bluesky:{uri}`, `mastodon:{url}`, `blog:{feed}:{id}`.
2. Build the collector from the Bluesky copy, then move Mastodon, Reddit and Blog onto it, one per PR. The team settles the counting rules first (see decisions).
3. Point the scheduler at `collect`. Delete its private-function imports and the URLs and limits it works out again for itself.
4. Load tickers once per batch for linking (today it is once per post). Write one "queue a stored artifact for analysis" function and share it with Marketaux.
5. Collapse the three "posts for ticker" queries into one, ranked by stored engagement. Delete `crud.artifact.get_bluesky_posts_for_ticker` and `get_mastodon_posts_for_ticker`, which lost their only caller in #64.

Tests
- Replace the 7-patch `test_social_collectors_link_each_saved_artifact` with collector tests on Postgres using fake adapters.
- Run the `ExampleAdapter` contract test against all four real adapters.

Watch out for
- Changing the hash formats would insert every existing row again.
- Several things depend on the current collectors: the scheduler Lambda, the backfill script, the analysis source set and `/reddit/ticker-sentiment`.

Where the code is: `backend/app/api/routes/reddit.py:23-230`, `bluesky.py:26-234`, `mastodon.py:26-228`, `blog.py:29-284`, `backend/lambdas/public_discussion_schedule.py:39-150`, `backend/app/schemas/public_discussion.py:17-92`, `backend/app/services/public_discussion.py:195-242`, `backend/app/crud/artifact.py:206-364`.

## Phase 3: analysis

### 06 Structured generation

Strong, size M. Needs Phase 0. Unblocks 07. Test approach: a third-party service (Bedrock, Groq and a scripted fake).

What is wrong
- `llm.py` mixes five prompt builders, parse and repair logic, an inline Groq adapter and a private if/elif provider switch.
- Callers pick the prompt version themselves, token budgets are set per Lambda instead of per summary kind, and callers match on error message text.
- The providers behave differently. Bedrock raises on an oversize prompt, while Groq silently cuts it short. The category prompt has no input cap at all. Five repair fixes landed on one day (2026-08-31).

What to build

One structured generation module with one entry point: "generate a validated X". It returns either a typed result that records the model and prompt version, or an explicit "unavailable" result. A small provider interface sits behind it, with three adapters: Bedrock, Groq and a scripted test adapter.

Done in Phase 0
- `LLMUnavailableError` (`app/services/llm_errors.py`) is raised by both providers and caught in `parsing/analysis.py`. ApiFunction's output budget is 4096 (#58).
- `test_llm_unavailable.py` covers "unavailable means sentiment is stored with no summary" for both providers (#58).
- The `gemini.py` and `groq.py` shims are deleted (#64).

Steps still to do
1. Pull the provider interface out of `_call_llm`. Move the inline Groq code into its own adapter next to `bedrock.py`, and add the scripted adapter.
2. Put each summary kind behind the module with its own input and output budget. The kinds are announcement, news, discussion, Reddit digest and category split.
3. Return the model and prompt version in the result, and remove the `active_model_name()` calls from the 8 callers.
4. Rename the `/gemini` routes the next time the frontend changes.

Tests: move `test_bedrock.py:154-292`, which patches the private `_call_llm`, onto the scripted adapter through the public interface.

Watch out for
- The admin routes still catch any `RuntimeError` and return 500 (gemini) or 503 (reddit). When they move behind the module, return 503 for "unavailable".
- The API Lambda and API Gateway both stop at 30 seconds. With 4096 output tokens, an admin summary could get close to that.

Where the code is: `backend/app/services/llm.py:21-535`, `backend/app/services/bedrock.py:68-108`, `backend/parsing/analysis.py:390-506`, `backend/app/api/routes/gemini.py`, `backend/app/services/news_summary.py`, `infra/template.yaml:451,652`.

### 07 Artifact summary

Strong, size M to L. Needs 06 and the two citation branches merged. Unblocks 08 and 10. Test approach: real Postgres.

What is wrong

The six-field summary (`summary`, `about`, `changed`, `matters`, `confirmed_facts`, `speculation`) has no single owner.
- Its shape is worked out again in 11 backend modules and 3 frontend components.
- It is stored twice: as JSON fields and again as a combined `summary_text`, and the two can drift apart.
- Four different rules decide whether a summary is complete.
- The writers disagree. `storage.py` drops `confirmed_facts`, `speculation` and `prompt_version`, and the Lambda write path lacks the race-safe upsert (`recommendations.md` §2.3).
- The readers disagree. The same artifact shows "Summary pending." on one page and "No impact summary available yet." on another.

What to build

One artifact summary module that owns the record, the completeness check when it is written, storage, recovery of old records, and the views callers need (card, clarity, alert text and brief).

Done in Phase 0: the news summary route and the local loader use `upsert_artifact_summary` instead of inserting (#62).

Steps still to do
1. Move every other writer onto one "record summary" function: a race-safe upsert that joins the caller's transaction. Keep today's storage. About 6 files change.
2. Check completeness when recording. Delete the four "is it summarised?" variants and the four "combine into text" functions.
3. Move the readers onto views. Merge the announcement and ticker card formatters, including the acronym fix, the source labels and the fallbacks. About 5 files change.
4. Serve the watchlist brief from a view instead of raw `artifact_metadata`.
5. Optional, later: collapse the two stores into one with a data migration (see decisions).

Tests
- Replace these with "record then view" round trips on Postgres: `test_summary_metadata.py:48-91` (a MagicMock whose `side_effect` depends on call order) and the metadata assertions in `test_news_summary.py` and `test_apis.py`.
- Add one test that every writer produces the same view.

Watch out for
- Some readers need the six keys at the top level of `artifact_metadata`: the category-sentiment keyword search and the frontend watchlist. Keep writing those keys until step 4 lands.
- Merge the two citation branches first.

Where the code is: `backend/lambdas/analysis.py:322-442`, `backend/app/crud/artifact.py:38-110`, `backend/app/api/routes/gemini.py:18-82`, `backend/app/services/news_summary.py:15-64`, `backend/parsing/storage.py:48-163`, `backend/app/services/summary_metadata.py`, `backend/app/crud/announcement.py:88-157`, `backend/app/api/routes/ticker.py:235-588`, `backend/lambdas/notify.py:175`, and in the frontend `AnnouncementCard.jsx`, `ClarityLayer.jsx` and `watchlist/page.jsx:79`.

### 09 Category taxonomy ownership

Worth exploring, size S to M. Needs Phase 0. Unblocks 10. Test approach: pure code.

What is wrong
- The classification engine itself is good, but adding a category still means editing 7 places: the taxonomy, `EXTRACTORS`, `CATEGORIES`, the storage `artifact_type` map, `_LEGACY_TO_STABLE`, the `ArtifactType` enum and the sentiment keywords.
- 4 of the 7 extractor classes return `{}`.
- The documented legacy baseline now silently runs rules-v2, so the recorded Macro F1 of 0.4765 can no longer be reproduced.

What to build

Each category definition owns its own facts: its rules, an optional extractor, a display label, the stored `artifact_type` and its sentiment bucket. `classify_document` does not change, so this stays in line with the classification implementation plan.

Steps
1. Freeze the recorded legacy baseline as a fixture. Delete `parsing/classifier.py` and `--classifier legacy`.
2. Delete the empty extractor classes and the `CATEGORIES` list.
3. Add a label, an `artifact_type` and a sentiment bucket to each definition, and generate the other maps from them.
4. Hand the bucket mapping to 10.

Tests: keep `test_classification.py` as it is. Add one test that every definition is complete.

Watch out for
- The stored `category` and `artifact_type` values must not change.
- #62 changed how `category_sentiment.py` matches keywords: whole words only, and stored names such as `security_notification` count as one word. Take this into account when the bucket mapping moves here.

Where the code is: `backend/parsing/classification/taxonomy.py:29-309`, `backend/parsing/extractors.py:17-25`, `backend/parsing/categories/`, `backend/parsing/classifier.py:196-210`, `backend/parsing/storage.py:41-45`, `backend/tools/evaluate_classification.py:19-38`, `backend/app/schemas/artifact.py:19-29`, `backend/app/api/routes/category_sentiment.py:28-67`.

### 08 Artifact analysis

Strong, size L. Start after 03, 04, 06 and 07. Test approach: services we own, behind interfaces with fakes.

What is wrong
- "Analyse an artifact and record the result" exists as 3 to 5 near-copies.
- `artifact_type` depends on which path brought the item in.
- The analysis Lambda imports crud inside functions 15 times.

What to build

One artifact analysis module with interfaces for the document store (03), the sentiment scorer (FinBERT plus a fake), generation (06) and persistence (07). The Lambda becomes a thin event handler. Every other entry point either calls the module or queues the work.

Done in Phase 0: the team chose title + raw_text as the one FinBERT input. `sentiment.sentiment_input(title, raw_text)` is used by the worker, the news route and the local loader, and the tests that disagreed were fixed (#62).

Steps still to do
1. Pull a shared "analyse text" out of the three `analyse_*` functions.
2. Merge the Lambda's two lifecycles and its two `_mark_failed` functions (and the `_record_retry` added in #61), using the stage outcome from 04.
3. Introduce the interfaces.
4. Point the admin routes, the Marketaux inline mode and the local loader at the module, or delete them in favour of queueing.
5. At the next change to the message contract, rename `PublicDiscussionAnalysisMessage`, because it also carries news.

Tests
- Replace the event-order monkeypatch tests in `test_document_workers.py:709-842` and `1138-1290` with behaviour tests that use fakes at the interfaces.
- Fold `test_news_sentiment` and `test_news_summary` into them.

Where the code is: `backend/parsing/analysis.py:356-520`, `backend/lambdas/analysis.py:518-784`, `backend/parsing/storage.py:68-316`, `backend/app/services/news_sentiment.py:28-49`, `backend/app/services/news_summary.py`, `backend/app/services/marketaux.py:31-47,275-332`, `backend/app/api/routes/gemini.py:130-231`.

## Phase 4: read side

### 10 Ticker read-models

Strong, size M. The bucket remap in step 3 is only worth exploring. Needs 01, 07, 09 and the citation branches merged. Test approach: real Postgres, plus a fake quote service.

What is wrong
- `ticker.py` is 597 lines with 22 commits, and mixes catalogue data, a Yahoo quote client and about 20 formatters.
- Category buckets are guessed by matching keywords in LLM prose, ignoring the rules-v2 classification.
- The watchlist builds its own read-model in the browser. It makes N+1 calls, downloads every artifact including `raw_text`, and dropped sentiment from the cards to cope.

What to build

Ticker brief, category sentiment and watchlist summary become read-model modules outside the route files, sharing the card view from 07. Quotes come through an interface with a Yahoo adapter and a fake.

Done in Phase 0
- The `confidence or 1.0` weighting bug is fixed, and keywords match whole words only (#62).
- The dead `category_sentiment.py` helpers and the `/overview` and `/brief-aside` routes are deleted (#64).

Steps still to do
1. Move brief building and the Yahoo client out of `ticker.py` into a ticker brief read-model behind a quote interface.
2. Move `read_ticker_category_sentiment` into its own module. Fold in the headline "latest signal" (`ticker.py:330-338`), so ticker sentiment has one definition.
3. The team agrees the mapping from taxonomy `primary_category` to bucket, because the numbers in the UI will change (see decisions). Then replace the keyword matching.
4. Add a watchlist summary endpoint. Delete the page's private `fetchJson` and the dead `{tickers: [...]}` branch in search.
5. Batch the deep-dive timeline's per-artifact summary query.
6. Optional: drop `"tone": "green"` from the deep-dive payload after `DeepDiveTimeline.jsx` hard-codes `styles.green`.

Tests
- Replace `test_apis.py:34-270`, which patches internals, with Postgres read-model tests plus a fake quote service. Follow the style of `test_database.py:908-963`.
- Replace the source-text assertions in `test_deployment_contracts.py:52-66` with a behaviour check: the API image cannot import `transformers`.

Where the code is: `backend/app/api/routes/ticker.py:20-597`, `backend/app/api/routes/category_sentiment.py`, `backend/app/crud/announcement.py:25-162`, `backend/app/api/routes/artifact.py:18-23`, `backend/app/crud/artifact.py:30-31`, `frontend/src/app/watchlist/page.jsx:21-137,244`, `frontend/src/app/search/page.jsx:36-46`, `frontend/src/app/components/ticker/DeepDiveTimeline.jsx`.

## Alerts track

### 13 Email sender port

Strong, size S to M. Do this first on the alerts track. Unblocks 12 and 14. Test approach: a third-party service (Brevo, dry-run and a recording fake).

What is wrong

The email provider has no real seam, so the notify worker and the preferences route each interpret Brevo failures themselves, and they do it differently. Notify looks for the word "recipient" in a `ValueError`. The route turns an invalid recipient into a 500. Dry-run knowledge is split between modules. The SES to Brevo swap (`c244ab7`) touched 27 files.

What to build

An email sender interface that returns plain outcomes: accepted, recipient rejected, unavailable or misconfigured. Three adapters sit behind it: Brevo, dry-run and a recording fake for tests. Each caller decides what an outcome means for it: a ledger status in notify, an HTTP status in the route.

Done in Phase 0: the broken one-click unsubscribe is fixed by no longer sending `List-Unsubscribe-Post` (#62). Real one-click support is optional. It would need an API-backed POST endpoint behind the `/api/*` CloudFront behaviour, added to the public allowlist in `test_access_policy.py`.

Steps still to do
1. Define the outcomes, and wrap `brevo_alerts` as the Brevo adapter (its internals stay).
2. Move send pacing and dry-run into the adapters.
3. Switch notify and the route to the interface.

Tests
- Keep `test_brevo_alerts.py` as the Brevo adapter test.
- The notify and route Brevo-error tests become scenarios using the recording fake.

Where the code is: `backend/app/services/brevo_alerts.py:23-204`, `backend/lambdas/notify.py:515-598`, `backend/app/api/routes/notification_preferences.py:147-189`, `infra/template.yaml:1107-1110`.

### 12 Alert delivery

Strong, size M. Needs 13. Test approach: real Postgres with a fake email sender.

What is wrong
- `_ensure_rollup` (`notify.py:665-707`) and `_process_watcher` (`notify.py:757-799`) repeat the same steps: check the budget, check the preferences are still current, render, send, record the result.
- The delivery status names are written out again in several files.
- The cap and budget checks are only correct because the claim is committed first, and only a test name says so.
- `test_notify.py` has 75 monkeypatches across about 15 private functions. Only the happy path and dedupe are tested end to end on Postgres.

What to build

One alert delivery module. Direct alerts and rollups become one decision that takes the kind as a parameter. A delivery ledger owns the claim, the result and the subscription mirror as one atomic step. One shared alert vocabulary (labels, the default rule and statuses) is used by the UI, the API and the pipeline.

Done in Phase 0: `app/alert_vocabulary.py` holds the alert labels and the default rule, and neutral alerts work end to end. `test_notify_database.py` now runs for negative and neutral (#60).

Steps still to do
1. Write handler-level scenario tests on Postgres with a fake sender. They should pass against today's code. Cover: hitting the cap and sending a rollup, budget suppression, an unverified recipient, preferences that changed, and a provider reject compared with a retry.
2. Merge the direct and rollup decision sequences, and make the "claim first" ordering explicit in code.
3. Collapse the five `mark_*` pass-through functions into one ledger transition that takes an outcome. Move the "D17" subscription mirror into the ledger. Add the delivery statuses to the shared vocabulary.
4. Delete the private-seam tests in `test_notify.py` and the duplicates in `test_alerts.py:139-298`.

Watch out for: keep the SQS `batchItemFailures` contract.

Where the code is: `backend/lambdas/notify.py:162-835`, `backend/app/crud/alert_delivery.py:106-406`, `backend/app/crud/alert_subscription.py:282-330`, `backend/app/models/alert_delivery.py:51`, `backend/app/crud/alert_rule.py:20`, `backend/app/schemas/notification.py:9-19`, `backend/app/alert_vocabulary.py`, `frontend/src/app/settings/notifications/page.jsx:12-47`.

### 14 Alert subscription lifecycle

Worth exploring, size M. Needs 13. Test approach: real Postgres with a fake email sender.

What is wrong
- The preferences route holds logic that belongs in a module: the verification state machine, the resend rate limit, token creation, resolving an unsubscribe, and undoing changes when sending fails.
- In crud, `update_verification_state` takes 8 parameters, including three compare-and-set guards, and its five callers each pass a different mix.
- Link building appears in both notify and the route. The SHA-256 regex appears three times. Email addresses are normalised two different ways.

What to build

One alert subscription module with five operations: save, request verification, confirm, unsubscribe, and build links. The route only translates HTTP, and notify asks the module for links.

Steps
1. Write an end-to-end scenario on Postgres with a fake sender: enable alerts, verify, unsubscribe through the alert link, and end up disabled.
2. Move the state machine, the rate limit and the undo logic from the route into the module.
3. Merge the token key derivation and the hash regexes. Use one link builder, and prefer `SiteUrl`.
4. Normalise email addresses one way, with `email_validator`.

Where the code is: `backend/app/api/routes/notification_preferences.py:59-536`, `backend/app/crud/alert_subscription.py:119-373`, `backend/app/services/verification_tokens.py`, `backend/app/services/unsubscribe_tokens.py`, `backend/lambdas/notify.py:493-512`.

## Deploy and configuration track

### 16 Release parameters

Strong, size M. Needs 15. Unblocks 18. Test approach: a service we own, with a `--dry-run` mode.

What is wrong
- Stack parameters and the function-to-ECR map are written out about 7 times per parameter in `deploy-staging.yml`, again in the rollback workflow, and in three README copies.
- The `describe-stacks … Outputs` query appears 23 times.
- The schema-drift script differs between `validate-branch.yml` and `deploy-staging.yml`.

What to build

One release module that produces the `sam deploy` command for a release or a rollback. Image functions come from the template model (`TemplateModel.image_functions()` in `backend/tools/template_model.py`). Each parameter resolves in this order: explicit override, then the live stack's value, then the template default. A rollback is the live parameters with the image SHAs swapped.

Done in Phase 0 (#59)
- The rollback workflow reads the live stack's parameters, changes only the three image URIs, and maps NotificationFunction.
- `FrontendBaseUrl` uses `https://$SITE_DOMAIN_NAME` when `vars.SITE_DOMAIN_NAME` is set.

Steps still to do
1. Check the #59 rollback on staging: run "Prepare staging backend rollback" once. It only creates a change set. The only parameter changes should be the three image URIs.
2. Write the release script in Python on top of the template model, with a `--dry-run` flag.
3. Switch the rollback workflow to the script first, because it runs less often. Check it on staging with `--no-execute-changeset`, then switch `deploy-staging`.
4. Replace the README command copies with a pointer to the script, and dedupe the schema-drift script.
5. Handle a brand-new stack that has no `FrontendUrl` output yet.

Tests: one dry-run test replaces the remaining substring checks in `test_deployment_contracts.py:203-280` and `422-441`. It checks that every parameter without a default is supplied and every image function is mapped. (#59 already added rule-based versions of the last two checks.)

Where the code is: `.github/workflows/deploy-staging.yml:8-507`, `.github/workflows/prepare-staging-backend-rollback.yml`, `infra/README.md:238-532`, `infra/template.yaml:5-127`, `.github/workflows/validate-branch.yml:63`.

### 17 Runtime configuration

Worth exploring, size M to L. Needs 15. Test approach: a service we own (SSM behind an interface).

What is wrong
- `Settings` is built when `app.core.config` is first imported, so SSM secrets must be loaded before anything imports it. Only comments state that rule, and `test_notify.py:846-856` enforces it by comparing where lines sit in the source file.
- The Lambdas skip `Settings`, read the environment again with their own defaults, and the source-URL override applies to manual scrapes but not scheduled ones.

What to build

One configuration module that is built the first time it is used. It declares every setting once, with its limits, and resolves `*_PARAMETER` secrets itself. A secrets registry lists each secret, and the template model (15) checks that registry against the environment variables and IAM grants.

Done in Phase 0
- The 15 unread `Settings` fields and the stale `GROQ_API_KEY_PARAMETER` in `.env.example` are deleted (#65, #62). So is `ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED` (#62).
- The document size limits now come from `lambdas/download_validation.py`, and `MAX_ANALYSIS_CHARS` from `sentiment.sentiment_input` (#62).
- Side effect: a malformed `MAX_*` or `DISCOVERY_LOOKBACK_DAYS` value no longer crashes the API at import. The Lambdas that read them still fail on bad input.

Steps still to do
1. Move the Lambda-only `os.getenv` settings into `Settings`, one at a time.
2. Add a secrets registry that `load_runtime_configuration` loops over, plus a template-model test that ties it to the environment variables and IAM grants.
3. Make `settings` lazy behind a module-level proxy, and delete the source-position test.

Watch out for: about 30 modules import `settings`, and many tests use `patch.object(settings, ...)`. The proxy has to keep that working.

Where the code is: `backend/app/core/config.py`, `backend/lambdas/common.py:71-123`, `backend/lambda_api.py:5-13`, `backend/lambdas/schedule.py:32-61`, `backend/lambdas/notify.py:36-39`, `backend/lambdas/public_discussion_schedule.py:39-64`, `backend/.env.example`.

### 18 OIDC role pair

Speculative, size S to M. Needs 16. Test approach: remote-owned (AWS IAM), so review by hand.

What is wrong
- The staging and deployment-test roles are two near-identical blocks of about 190 lines each.
- They have already drifted: only staging has the Route 53 statements.
- `d04b23b`, then its revert `b7ed1d6`, then the restore `167a23b` all happened within 30 minutes.
- Which grants each workflow needs is not written down anywhere.

Steps
1. Decide whether the deployment-test stack is still needed (see decisions). Deleting it may be the whole fix.
2. Lint `github-oidc.yaml` in CI.
3. Define the role pair once, with the prefix as a parameter. Review the change set by hand before running it, because this stack is deployed manually and is security-critical.

Where the code is: `infra/github-oidc.yaml:44-656`.

## Decisions still needed

| Decision | Candidate | Status |
|---|---|---|
| Which text FinBERT scores | 08 | Decided: title + raw_text, capped at `MAX_ANALYSIS_CHARS`. Done in #62. |
| Support neutral alerts or remove the option | 12 | Decided: support them end to end. Done in #60. |
| How to handle one-click unsubscribe | 13 | Decided for now: stop sending the header (#62). An API-backed endpoint is optional later. |
| Mapping from taxonomy category to sentiment bucket, and whether one artifact may count in several buckets | 10 | Open. #62 only fixed the keyword matching. The UI numbers will change when this is decided. |
| Whether `source_url` on Queue A is authoritative | 04 | Open. Discovery ignores it today and download uses it. |
| How to count a malformed public-discussion post: failure or duplicate | 05 | Open. |
| Which meaning `SUPPORTED_TICKERS` keeps, and what the other meaning is renamed to | 01 | Decided in #56: it means "enabled for manual scraping" (the `Settings` field and env var). The analysis worker's copy is gone; it accepts catalogue tickers directly. Revisit if the team wants a different name. |
| Whether to collapse the two summary stores after the views land | 07 | Open. |
| Whether the deployment-test stack is still needed | 18 | Open. |
