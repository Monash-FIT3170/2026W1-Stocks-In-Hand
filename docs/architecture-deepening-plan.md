# Architecture Deepening Plan

## In short

- This plan makes the parts of the code that change most often easier to change and easier to test. Those parts are the announcement pipeline, LLM analysis and summaries, the ticker API, investor alerts and deployment.
- The main idea is to take knowledge that is copied across many files and give it one home (a "module") with a small, clear interface. Tests then check that interface instead of private functions.
- The work is split into 18 pieces of work called candidates, grouped into phases. Phase 0 fixes live bugs and deletes dead code first, so the later work starts from a smaller and correct codebase.
- Phase 0 is done in #56. It was reviewed as PRs #57 to #65, which are being closed in favour of #56.
- Phase 1 (candidates 01, 15 and 11), Phase 2 (candidates 04, 03, 02 and 05), most of Phase 3 (candidates 06, 07 and 09), candidate 13 on the alerts track and candidate 16 on the deploy track are also done in this PR, #56. #56 is the one PR to merge. More candidates are still being finished in #56.
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
| 0 | Bug fixes and dead code | Phase 0 | Must do | L | none | Done in #56; reviewed as PRs #57 to #65 |
| 01 | Ticker catalogue | Phase 1 | Strong | M | Phase 0 | Done in #56 |
| 15 | Template model | Phase 1 | Strong | M | Phase 0 | Done in #56 |
| 11 | Access policy | Phase 1 | Strong (security) | S | Phase 0 | Done in #56 |
| 04 | Scrape run lifecycle | Phase 2 | Strong | M | 01 | Done in #56 |
| 03 | Raw document store | Phase 2 | Strong | M | 01 | Done in #56 |
| 02 | Source adapter per company | Phase 2 | Strong | L | 01 | Done in #56 |
| 05 | Public discussion collector | Phase 2 | Strong | M | 01 | Done in #56 |
| 06 | Structured generation | Phase 3 | Strong | M | Phase 0 | Done in #56 |
| 07 | Artifact summary | Phase 3 | Strong | M to L | 06 | Done in #56 (the watchlist brief is 10 step 4) |
| 09 | Category taxonomy ownership | Phase 3 | Worth exploring | S to M | Phase 0 | Done in #56 (the bucket switch is 10 step 3) |
| 08 | Artifact analysis | Phase 3 | Strong | L | 03, 04, 06, 07 | Partly done in Phase 0 |
| 10 | Ticker read-models | Phase 4 | Strong (bucket remap: worth exploring) | M | 01, 07, 09 | Partly done in Phase 0; step 5 done by 07 in #56 |
| 13 | Email sender port | Alerts track | Strong | S to M | Phase 0 | Done in #56 |
| 12 | Alert delivery | Alerts track | Strong | M | 13 | Partly done in Phase 0 |
| 14 | Alert subscription lifecycle | Alerts track | Worth exploring | M | 13 | Not started |
| 16 | Release parameters | Deploy track | Strong | M | 15 | Done in #56 |
| 17 | Runtime configuration | Deploy track | Worth exploring | M to L | 15 | Partly done in Phase 0 |
| 18 | OIDC role pair | Deploy track | Speculative | S to M | 16 | Not started |

"Strong" means the problem is clear and the fix is worth doing. "Worth exploring" means it is probably worth doing but needs a closer look or a team decision first. "Speculative" means it may not be needed at all.

The alerts track and the deploy track do not depend on the ingestion or analysis phases. A second person can work on them in parallel once Phase 0 has merged.

## Order of work

1. Merge #56. It is the one PR to merge. It holds this plan, Phase 0 (reviewed as PRs #57 to #65, which are being closed in its favour), Phase 1 (candidates 01, 15 and 11), Phase 2 (candidates 04, 03, 02 and 05), most of Phase 3 (candidates 06, 07 and 09), candidate 13 on the alerts track and candidate 16 on the deploy track. More candidates are still being finished in #56. It passes 972 backend tests with Postgres and LocalStack running; without LocalStack, its one LocalStack test skips. #56 adds three migrations (`86d9seedtickers`, `86d9statuschecks` and `86d9engagement`), which deploy runs; 07, 13 and 16 add none. It also fixes the analysis image, which could not import its handler (see 09), so check the analysis Lambda after the next deploy. The deploy, rollback and execute workflows now run `backend/tools/release.py`, so do the first staging runs in 16's Left over before relying on an automatic deploy.
2. Do not wait for the citation branches. `feature/86d4a0a1d-specific_report_sources` is not merged, and its change to `ticker._source_from_values` now belongs on `artifact_card.sources`. The two claim-traceability branches, `feature/86d2ba6e6-claim_source_traceability` (#68) and `feature/86d48cxxz-advanced_traceability`, define `claim_evidence` in incompatible ways and no longer merge. Pick one and rewrite it onto 07's `SummaryExtension` hook and the artifact card.
3. After that, follow the "Depends on" column. Phase 2 before Phase 3 before Phase 4, with the alerts and deploy tracks in parallel.

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
- The "Queue wiring regression tests" CI job installs only pytest and PyYAML, and runs `test_queue_wiring.py`, `test_deployment_contracts.py`, `test_template_model.py` and `test_release.py`. Keep those four files, and anything they import, free of other dependencies. Today that means `backend/app/sources.py`, `backend/tools/sync_tickers.py`, `backend/tools/template_model.py`, `backend/tools/verify_queue_wiring.py` and `backend/tools/release.py`.
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

Status: Done in #56; reviewed as PRs #57 to #65. Nothing here needs to be done again. This section records what each PR changed and what was left over.

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
| The analysis image could not import its handler: `Dockerfile.analysis` did not copy `parsing/classification/`, `parsing/extractors.py` or `parsing/classification_metadata.py` (since `9816ef6`). Found in #56 while doing 09. | #56 | The image copies them. `test_lambda_images.py` checks every image ships the backend modules its handler imports. |
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

- `"tone": "green"` in the deep-dive payload was kept because `DeepDiveTimeline.jsx` used it to colour the timeline dot. #42 deleted that component, and `DeepDiveNotebook.jsx` does not read `tone`, so 10 step 6 can drop it with no frontend change.
- `BaseScraper.download_pdf` is still used by `backend/scripts/populate_local_content.py` and still imports `lambdas.source_download` (candidate 02). Done in #56.
- `crud.artifact.get_bluesky_posts_for_ticker` and `get_mastodon_posts_for_ticker` became dead in #64 but were not on the list (candidate 05). Done in #56.
- `/headlines` and `/analyse` in `backend/main.py` were kept because they may still be used locally. `/analyse` now needs an admin session.
- If a Lambda times out on its final receive, its error handler never runs, so nothing records the final failure (candidate 04). Done in #56 with a sweep the schedule runs.
- With 4096 output tokens, an admin summary route could come close to the 30-second API Gateway limit (candidate 06). Still open after 06 in #56; 08 step 4 removes it.
- Run "Prepare staging backend rollback" once against staging to check the #59 change. It only creates a change set. The only parameter changes should be the three image URIs (candidate 16). 16 replaces the #59 rollback with the release module in #56, so run the #59 version from its branch (`bugfix/release_workflow_parameters`) before #56 merges, then the module's version, and compare (see 16's Left over). Still open.
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
5. `backend/tools/sync_tickers.py` rewrites the copies that cannot import Python: `frontend/src/app/ticker/tickers.json` (read by `generateStaticParams`), the CloudFront `tickerRoute` pattern and the `ScheduledTickers` default. Candidate 16 removed both `deploy-staging.yml` copies. The push fallback went with the bash resolution, and the manual input now defaults to `keep`. `test_ticker_list_copies_match_the_catalogue` fails when a copy is stale, and the queue-wiring CI job now runs on catalogue changes. The ApiFunction's `SUPPORTED_TICKERS` variable is removed because `Settings` already defaults to the catalogue.
6. The ticker list in `docker-compose-dev.yml` and the ticker and source-URL lines in `backend/.env.example` are removed.

To add an ASX ticker now: add a catalogue entry, write its source adapter (candidate 02) and add it to `ADAPTER_TYPES` in `backend/scrapers/registry.py`, record its pages with `python -m tools.record_source_pages <TICKER>` and pin them in `test_source_adapter_fixtures.py`, write a seed migration for the row, update `test_migration_seeds_the_catalogue_facts` to read it, and run `python -m tools.sync_tickers` in `backend/`.

Tests
- `test_ticker_catalogue.py`: normalisation, and Postgres tests for `ensure_ticker` (seeded row, catalogue facts, a repeat call, unknown symbol, placeholders filled and curated values kept).
- The text search in `test_deployment_contracts.py` is replaced by the sync check, and the AST check in `test_expanded_scraper_registry.py` by catalogue-wide scraper and object-key tests.
- The `_ensure_default_tickers` call-count tests in `test_apis.py` are deleted.

Left over
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

`backend/tools/template_model.py` parses the template once and answers questions about it: functions, the queue each function consumes, SendMessage targets (including grants under `!If`), environment variables, readable SSM parameter names, queue settings, dead-letter queues, the alarms watching a queue and the outputs that export it. Intrinsic functions keep CloudFormation's JSON form, so `!Ref` and `!GetAtt` can be told apart. It needs only PyYAML. 16 (#56) extends it with each parameter's default and constraints (`Parameter.problems`, `parameter_definitions`), the template's Rules (`rule_failures`), each image function's ImageUri parameter (`Function.image_parameter`, `image_parameters`) and the secrets a function reads only while a switch is on (`gated_secrets`).

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
- 16 (#56) replaced the deploy and rollback workflow text checks in `test_deployment_contracts.py` with PyYAML rules. The `github-oidc.yaml` text checks left for 18 are `test_github_oidc_can_check_brevo_parameter_metadata`, `test_cloudformation_role_can_poll_route53_dns_changes` and the OIDC lines of `test_marketaux_is_ssm_backed_bounded_and_release_gated` in `test_deployment_contracts.py`, plus `test_staging_github_role_can_read_only_application_queue_attributes` in `test_queue_wiring.py`. `test_staging_validation_workflow_cannot_deploy` belongs to neither 16 nor 18.

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

Strong, size M. Done in #56. Unblocks 08. Test approach: a service we own (real Postgres plus a fake queue sender).

What was wrong
- Each of the three workers repeated the same steps for every message: decode it, decide whether the error is permanent or retryable, record the outcome and log it.
- "Request a scrape run" was copied in the API (`main.py`) and the scheduler (`schedule.py`), and the copies disagreed. Only the API honoured the `{TICKER}_SOURCE_URL` override. The discovery worker ignored `source_url`, while the download worker used it.

What was built

Requesting a run lives in `app/services/scrape_runs.request_scrape_run`, with the queue sender passed in. Recording a stage outcome lives in `lambdas/pipeline_stage.run_stage`: a permanent failure is final, a retryable failure records the attempt only, and the final receive is final. Each worker names the run or artifact a record is about (its subject) and the error codes that must not be recorded against it.

Done in Phase 0 (#61)
- Retryable failures record the error only, and the final receive or a permanent error calls the `mark_*_failed` transition.
- `test_transient_failures.py` drove the real handlers against Postgres. #56 renames it `test_pipeline_stages.py` and extends it.

Done in #56
1. `request_scrape_run` is the one way to request a run, for the API and the schedule. The team decided the catalogue is authoritative for the source, so the `{TICKER}_SOURCE_URL` override (`settings.SOURCE_URLS`) is gone and both record the catalogue's page and adapter.
2. `run_stage` replaces the three workers' copies of the record skeleton, including the `_mark_failed` and `_record_retry` pairs and the analysis worker's separate stored-text failure path.
3. "running" and the stored-text "queued" are `ScrapeRunStatus.RUNNING` and `AnalysisStatus.QUEUED`, and every status write uses the enums. Migration `86d9statuschecks` adds CHECK constraints on `scrape_runs.status`, `artifacts.download_status` and `artifacts.analysis_status` (`recommendations.md` §3.2). They are `NOT VALID`, so only new writes are checked.
4. The `"csl"` defaults are gone from `QueueAMessage`, `QueueBMessage` and `get_or_create_artifact`. Every producer already set the field, so the wire format does not change.
5. A Lambda that times out on its final receive never runs its error handler. `crud.scrape_run.fail_abandoned_work` fails queued, discovering and running runs, downloads and analyses that have not moved for 24 hours (`ABANDONED_AFTER`, longer than any queue's redelivery window, which a template-model test checks). The weekly schedule runs it first. A message redriven from a dead-letter queue still completes its artifact.

Tests
- `test_scrape_run_requests.py` runs the module, the route and the schedule handler on Postgres with a fake sender. It replaces the MagicMock request tests in `test_scrape_pipeline_api.py`, `test_schedule.py` and `test_source_adapters.py`.
- `test_pipeline_stages.py` covers discovery, download and analysis on Postgres with a fake adapter, SQS and an in-memory raw document store. It replaces the string-path monkeypatch tests in `test_document_workers.py` and `test_source_adapters.py`.
- `test_status_constraints.py` checks each status column accepts exactly its enum.
- The real-Postgres state-machine tests in `test_database.py` are kept.

Left over
- The CHECK constraints are `NOT VALID`. Run `SELECT status, count(*) FROM scrape_runs GROUP BY status` (and the same for the two artifact columns) on staging; if every value is in `app/status.py`, run `ALTER TABLE ... VALIDATE CONSTRAINT` for each.
- `items_failed` is read only by the run status and the admin `/scrape-runs` response, not by the frontend.
- The notify worker keeps its batch-item-failure pattern, as planned.
- The abandoned-work sweep runs only when `ScheduleEnabled` is true.

Where the code is: `backend/app/services/scrape_runs.py`, `backend/lambdas/pipeline_stage.py`, `backend/lambdas/discovery.py`, `backend/lambdas/download.py`, `backend/lambdas/analysis.py`, `backend/lambdas/schedule.py`, `backend/app/crud/scrape_run.py`, `backend/app/status.py`, `backend/alembic/versions/86d9statuschecks_check_pipeline_status_values.py`.

### 03 Raw document store and validated document

Strong, size M. Done in #56. Unblocks 08. Test approach: real LocalStack, plus an in-memory store for worker tests.

What was wrong
- The S3 key was split between two workers: the download worker wrote `raw/{ticker}/{artifact_id}/{sha256}.{ext}` and the analysis worker read it back with its own regex.
- Both workers marked the artifact as stored, each its own way.
- A `DownloadedDocument` did not prove it was validated, so it was validated again at four points, and `document_too_large` was raised in 7 places.

What was built

`validated_document` (in `lambdas/download_validation.py`) is the only way to build a `DownloadedDocument`; its checksum and content type are derived from the validated bytes. `lambdas/raw_documents.RawDocumentStore` owns, for both workers, the key layout and parsing (`locate`), the object metadata, "put only if absent", "is it still there", "read and verify" and "is this object the document its key names" (`verify`). It sits on an `ObjectBucket`: `S3Bucket` for AWS and LocalStack, `InMemoryBucket` for tests.

Done in Phase 0
- The size limits agree with the template and live in `lambdas/download_validation.py` (#62).
- The `DownloadedPdf` alias, the `download_pdf` shim and the unused `final_url` parameter are gone (#63).

Done in #56
1. Only validation builds a `DownloadedDocument`, so the download worker's re-checks of size, checksum, format and content type are gone. `ensure_within_size_limit` raises `document_too_large` for the early checks.
2. The store owns key building and parsing, the metadata headers, put-if-absent and read-and-verify. The key layout, headers and error codes are unchanged, so the `raw/` notification filter still matches; a test ties the key prefix to the template's filter.
3. Reconciling an S3 event that arrives before the download commit goes through `store.verify` and `DocumentLocation.is_recorded_as`, and both workers mark an artifact stored from the store's `StoredDocument`.
4. `raise_for_document_status` is the one HTTP status rule for every download path.

Tests
- `test_raw_documents.py` covers the store in memory and once against LocalStack S3 (it skips when LocalStack is not running; set `LOCALSTACK_ENDPOINT_URL` if it is not on `localhost:4566`).
- The worker scenarios use the in-memory store; the literal key-string tests are deleted, and the `httpx.MockTransport` download tests are kept.

Left over
- The LocalStack test does not run in CI. Starting LocalStack in the backend CI job would run it.

Where the code is: `backend/lambdas/raw_documents.py`, `backend/lambdas/download_validation.py`, `backend/lambdas/download.py`, `backend/lambdas/analysis.py`, `backend/tests/test_raw_documents.py`.

### 02 Source adapter per company

Strong, size L. Done in #56. Test approach: a third-party service (13 real adapters plus recorded pages).

What was wrong
- Each company's knowledge was split between a discovery scraper, which wrote hints into an untyped `Announcement.metadata` dict, and the download resolver in `lambdas/source_download.py`, which read them back. Constants such as the YourIR app IDs and the Wesfarmers row selector were copied on both sides.
- 11 of the 13 scrapers had no offline tests.
- A page that failed to load returned `[]`, so a broken site looked like "no new announcements".

What was built

`scrapers/adapter.SourceAdapter`: one adapter per company (`scrapers/companies/*.py`) owns "list recent documents", "fetch one document" and its allowed hosts. Queue B's `metadata` still carries the adapter's hints, so the message schema did not change. Each adapter has a thin fetch step, which asks a web session from `scrapers/fetching.py` for pages, and a pure parse step over the HTML (`scrapers/html.py`, a small dependency-free document model). The live session marks each element's CSS display before serialising a page, so parsing sees the same line breaks and hidden text a browser's `innerText` would. Sites share family code: `scrapers/yourir.py` (ANZ, CBA, TCL), `scrapers/article_listings.py` (Macquarie, Origin, Rio Tinto, Woodside), `scrapers/miraqle.py` (Coles, Telstra) and `scrapers/parsing.py` (dates and de-duplication). `lambdas/source_download.py` is deleted.

Done in #56
1. The local loader downloads the way the worker does, and `BaseScraper.download_pdf`, `scrape` and the `scrapers` to `lambdas.source_download` import are gone.
2. Every company sits behind `SourceAdapter`, through a compatibility registry at first (`ADAPTERS`, `adapter_for`, `adapter_named`).
3. The YourIR family reads the JSON feed its widget reads, over plain HTTP, and downloads without a browser. Every company's hosts, referer rules and app IDs live in its adapter.
4. Every adapter is a fetch step plus a pure parse, with pages recorded from the live sites on 2026-10-07 (`tools/record_source_pages.py`). On that day the new parsers listed the same documents as the old scrapers, item for item, for the eight sites that worked, and one live download per adapter succeeded.
5. A site that cannot be reached raises `SourceUnreachableError` (retried) and a page with nothing the adapter can read raises `LayoutChangedError`, which discovery records as a permanent `source_layout_changed` failure.
6. The family helpers replace the copies (9 dedupe, 5 date-pattern and 5 date-format copies), about 300 lines. Over the whole candidate, the scrapers package and `lambdas/source_download.py` went from about 3,370 lines to 2,710, while gaining the HTML model, the fetch sessions and the recording tool.

Tests
- `test_yourir_adapters.py` and `test_source_adapter_fixtures.py` list and fetch through each adapter from recorded pages, and pin the first document and the count, because a changed document URL or source ID would rediscover stored documents.
- `test_source_html.py` and `test_source_parsing.py` cover the shared parsing code; `test_source_adapter_registry.py` covers the registry.
- The tests that reached into `_validated_url`, `_ADAPTER_HOSTS` and `_request_referer`, the AST convention test and the browser source-scanning test are deleted.

Behaviour changes
- `published_at` for ANZ, CBA and TCL comes from YourIR's UTC timestamp. TCL used to read Sydney time as UTC, 11 hours out.
- ORG's listing waited for network idle, which the site never reaches, so it always listed nothing; it now lists its releases again.
- On 2026-10-07 BHP answered browsers on our network with an Akamai 403, and its static page has no announcement list, so BHP runs, which used to complete with 0 items, now fail with `source_layout_changed`. BHP is a scheduled ticker.

Left over
- Check BHP from staging: if AWS is not blocked, record its pages with the tool; otherwise BHP needs a new listing (its market announcements now live under `/investor-centre/`).
- Macquarie titles include the date, "PDF" and file size, and Wesfarmers titles include the file size. These were already so and are pinned as they are.
- The package is still called `scrapers` (the Dockerfile copies it by name). Rename it to `source_adapters` with the next scraper image change if wanted.
- Re-record a site's pages when its layout changes and update the pinned expectations.

Where the code is: `backend/scrapers/adapter.py`, `backend/scrapers/registry.py`, `backend/scrapers/fetching.py`, `backend/scrapers/html.py`, `backend/scrapers/parsing.py`, `backend/scrapers/yourir.py`, `backend/scrapers/article_listings.py`, `backend/scrapers/miraqle.py`, `backend/scrapers/companies/*.py`, `backend/tools/record_source_pages.py`, `backend/tests/fixtures/sources/`.

### 05 Public discussion collector

Strong, size M. Done in #56. Test approach: a third-party service (4 real adapters plus recorded posts).

What was wrong
- Four route modules copied the same code: platform get-or-create, content hashing, the store loop, the run lifecycle and the enqueue step.
- The copies had drifted. Malformed posts counted as duplicates for Bluesky and Mastodon but as failures for blogs, and a Bluesky post with an empty timestamp aborted the whole batch.
- `PublicDiscussionAdapter` had no real implementations, and the scheduler imported eight private route functions and skipped target validation.

What was built

Four thin discussion sources in `app/services/discussion_sources/` (Reddit, Bluesky, Mastodon, blogs) each validate their target, fetch, and turn a raw post into the artifact to store with its identity and engagement. `app/services/discussion_collector` owns everything else: de-duplication by content hash, ticker linking, queueing for analysis, failure counting and the run lifecycle. The routes and the scheduler both call `request_collection` and `collect`.

Done in #56
1. Postgres characterisation tests pin the content-hash formats `reddit:{id}`, `bluesky:{uri}`, `mastodon:{url}` (or `mastodon:{instance}:{id}`) and `blog:{feed}:{id}`, and the stored fields.
2. The collector was built from the Bluesky copy, then Mastodon, Reddit and blogs moved onto it, one commit each. The team decided a malformed post is a failure: it counts in `items_failed` and its run ends partial. `items_found` counts every fetched post. The unused contract scaffolding (`PublicDiscussionAdapter`, `CollectionStatus` and friends) is replaced by the real `DiscussionSource` interface, and the `ExampleAdapter` test is now a contract test every real source keeps.
3. The scheduler calls the collector, validates each target with its source, and no longer imports route functions or works out URLs and limits again.
4. The collector loads the tickers once per collection, and `analysis_queue.queue_stored_text` is the one "queue stored text for analysis" function for public discussion, Marketaux and the pending-analysis requeue.
5. The collector stores each post's engagement, and migration `86d9engagement` fills it in for posts stored before. `get_discussion_posts_for_ticker` replaces the three "posts for ticker" queries; the two dead ones are deleted.

Tests
- `test_public_discussion_collector.py` pins identities and covers the run counts, malformed posts, duplicates, fetch failures, queueing and ranking on Postgres, and checks each source's engagement rule against the backfill.
- `test_public_discussion_schedule.py` runs the schedule handler on Postgres with a fake fetch.
- The 7-patch `test_social_collectors_link_each_saved_artifact` and the MagicMock schedule tests are deleted.

Behaviour changes
- Malformed posts are failed items, so Bluesky, Mastodon and Reddit runs can now end partial.
- A configured schedule target its source rejects counts as a failed collector.
- A post with no title and no text is no longer queued for analysis.

Left over
- The routes still run collection in FastAPI background tasks inside the API Lambda, which may freeze after the response. The abandoned-work sweep (04) fails runs left running for a day.

Where the code is: `backend/app/services/discussion_collector.py`, `backend/app/services/discussion_sources/`, `backend/app/services/analysis_queue.py`, `backend/app/api/routes/{reddit,bluesky,mastodon,blog}.py`, `backend/lambdas/public_discussion_schedule.py`, `backend/app/crud/artifact.py`, `backend/alembic/versions/86d9engagement_store_discussion_engagement.py`.

## Phase 3: analysis

### 06 Structured generation

Strong, size M. Done in #56. Unblocks 07. Test approach: a third-party service (Bedrock and Groq adapters, plus a scripted provider).

What was wrong
- `llm.py` mixed five prompt builders, parse and repair logic, an inline Groq adapter and a private if/elif provider switch.
- Callers picked the prompt version themselves and asked `active_model_name()` for the model. Token budgets were set per Lambda instead of per summary kind. The admin routes turned any `RuntimeError` into a 500.
- The providers behaved differently. Bedrock raised on an oversize prompt, while Groq cut the end off the whole prompt, which for a Reddit digest removed the answer format. The category prompt had no input cap. Five repair fixes landed on one day (2026-08-31).

What was built

`app/services/generation` has one entry point, `generate(kind)`. Each kind (`AnnouncementSummary`, `NewsSummary`, `DiscussionSummary`, `RedditDigest`, `CategorySplit`, in `kinds.py`) owns its prompt, its prompt version, its answer parser, any repair, and its budget: how much source text it reads and how many tokens it may write. `generate` returns `Generated` (the value, the model and the prompt version), or `Unavailable` when no provider is switched on. A malformed answer raises `ValueError` after the kind's repairs, and a failure worth retrying raises `RuntimeError`. Behind it, the `TextProvider` interface has three adapters: Bedrock, Groq, and `ScriptedProvider` for tests. `configured_provider()` picks one from `LLM_PROVIDER`. The module cuts each kind's source text to its budget. When a provider refuses a prompt as too long (`PromptTooLargeError`), it shortens the source text, keeps the instructions, and asks once more. `classify_document` is untouched and still has no provider ports.

Done in Phase 0
- `LLMUnavailableError` (`app/services/llm_errors.py`) is raised by both providers and caught in `parsing/analysis.py`. ApiFunction's output budget is 4096 (#58).
- `test_llm_unavailable.py` covers "unavailable means sentiment is stored with no summary" for both providers (#58).
- The `gemini.py` and `groq.py` shims are deleted (#64).

Done in #56
1. The `TextProvider` interface and its Bedrock, Groq and scripted adapters. The Bedrock adapter takes its runtime client and the Groq adapter its transport, so their tests no longer patch module internals.
2. Each summary kind sits behind `generate` with its own budget. Every kind asks for 4,096 output tokens, the value both Lambdas already used, and `BEDROCK_MAX_OUTPUT_TOKENS` is removed from the template, `Settings` and the examples. The category split reads at most 24,000 characters per call. Bedrock and Groq both raise `PromptTooLargeError`, and the module refits the prompt.
3. Callers read the model and prompt version from the result: the three analysis paths, the worker's summary repair, the local loader, the news summary service, the admin routes and the Reddit digest. `llm.py` and `active_model_name()` are deleted. The five sentiment bucket names move to `app/sentiment_buckets.py`.
4. The team decided to rename the `/gemini` routes now, with no alias. They are `/llm/categorise/recent`, `/llm/summarise/ticker/{symbol}` and `/llm/summarise/artifact/{artifact_id}` (`app/api/routes/llm.py`). The frontend never called them.

Tests
- `test_generation.py` runs `generate` with the scripted provider. It covers provenance, unavailability, repairs, the known GPT-OSS defects, each kind's input budget, the default Bedrock limit, refitting a refused prompt, and Groq's 413 keeping a digest's instructions. It replaces the `_call_llm` tests in `test_bedrock.py` and the parser tests in `test_apis.py`.
- `test_generation_providers.py` tests each adapter at its own boundary: a fake Bedrock client, and an httpx mock transport for Groq. It replaces `test_bedrock.py` and `test_groq.py`.
- `test_llm_routes.py` runs the admin routes and the Reddit digest on Postgres with a scripted provider, replacing the MagicMock route tests in `test_apis.py`. The worker, news summary and sentiment input tests script the provider instead of patching `llm` functions. The Reddit digest's login check moves into the access policy sweep.

Behaviour changes
- The admin summary and category routes answer 503 when no LLM is switched on, where they answered 500. The ticker-wide summary route stops with 503 instead of listing the same error against every artifact.
- The category split no longer fails on a chunk over Bedrock's 30,000-character limit. It reads the first 24,000 characters of each batch, newest artifacts first.
- On a Groq 413, the module shortens the source text and keeps the instructions, where Groq used to cut the end of the whole prompt. Groq is now sent each kind's output budget.
- Local runs that left `BEDROCK_MAX_OUTPUT_TOKENS` unset used 1,024 output tokens. Every kind now asks for 4,096.
- `/gemini/...` paths answer 404.

Left over
- With 4,096 output tokens and up to two repair calls, an admin summary route can still run past the 30-second API Gateway limit. 08 step 4 (queue the admin routes instead of generating inline) removes the risk. Tuning each kind's output budget from the Bedrock token logs would reduce it.
- `news_summary.summarise_news_artifact` turns `Unavailable` back into `LLMUnavailableError`, because its callers count it as a per-artifact error. 08 reshapes that path.
- The local loader (`parsing/storage.py`) dropped the prompt version and the clarity lists when it stored a summary. 07 fixed this in #56.
- No prompt text changed, so no prompt version changed.

Where the code is: `backend/app/services/generation/` (`__init__.py`, `kinds.py`, `providers.py`, `bedrock.py`, `groq.py`), `backend/app/services/llm_errors.py`, `backend/app/sentiment_buckets.py`, `backend/app/api/routes/llm.py`, `backend/app/api/routes/reddit.py`, `backend/parsing/analysis.py`, `backend/tests/test_generation.py`, `backend/tests/test_llm_routes.py`.

### 07 Artifact summary

Strong, size M to L. Done in #56, except serving the watchlist brief, which moves to 10 step 4. Unblocks 08 and 10. Test approach: real Postgres.

What was wrong
- The six-field summary (`summary`, `about`, `changed`, `matters`, `confirmed_facts`, `speculation`) had no single owner. Its shape was written out again in 11 backend modules, and six frontend readers depended on how the backend filled the gaps: `AnnouncementCard.jsx` with `recordPresentation.js`, the home page, `SourceLibrary.jsx` with `companyFormat.js`, `DeepDiveNotebook.jsx`, `ResearchSummary.jsx` (which replaced `ClarityLayer.jsx`) and `watchlist/page.jsx`.
- It is stored twice: as top-level keys of `artifact_metadata`, and joined into the `summary_text` of the artifact's one `artifact_summaries` row. Seven writers kept the two in step themselves, and every one committed on its own. `upsert_artifact_summary` rolled back the whole session on an `IntegrityError`, which threw away the caller's pending metadata change, so a race could leave the text and the fields disagreeing.
- Four rules decided whether a summary was complete, and four functions joined the lines into text. One rule wanted clarity lists for news, which never has them, so `/llm/summarise/ticker/{symbol}` summarised every news story again on each call.
- The writers disagreed. The local loader dropped both clarity lists and the prompt version, and overwrote a stored prompt version with NULL. The admin, news and loader writers stored the title as the summary text when an answer had no text. An eighth writer, `POST /artifact-summaries/`, wrote only the text, with no fields at all.
- The readers disagreed. The market feed showed a raw-text preview labelled as AI-assisted context. The ticker feed showed "Summary pending." and two other placeholder sentences. The brief story and the deep-dive detail fell back to a raw-text preview, then to placeholder sentences. Two tests required opposite fallbacks. The frontend kept two different lists of the backend's placeholder sentences so it could hide them.

What was built

`app/services/artifact_summary.py` owns the summary. A `Summary` holds the four text lines, the two clarity lists (None when the summary was never sorted into them), the model, the prompt version and any registered extensions. `from_answer` and `from_generated` clean a generated answer. `record(db, artifact, summary)` replaces both stores inside the caller's transaction and never commits or rolls back. It flushes the caller's pending changes first, because `SessionLocal` does not autoflush. Then one UPDATE swaps every summary key in `artifact_metadata` and keeps the caller's other keys, and an `ON CONFLICT` upsert writes the one summary row. It locks the artifact row before the summary row, as the worker does, so two recorders cannot deadlock. A summary with no text line raises `EmptySummary`. A partial summary is recorded. `read(artifact)` gives the summary back and recovers older rows that kept only the joined text. `WITH_SUMMARY` loads the summary rows of a list of artifacts in one more query. `is_complete` and `needs_summary` are the one completeness rule, and `incomplete_announcements` is the repair operation's selection. The views `brief`, `clarity` and `alert_text` show an artifact with no summary as None (unclassified for clarity), never as placeholder or raw text. `SummaryExtension` and `EXTENSIONS` (empty today) are the hook a claim-traceability design adds its field through, so `record`, `read` and `is_complete` carry it with no other change. `app/services/artifact_card.py` is the one artifact card both feeds show: tag, title, source name, link label, link, and the about, changed and matters lines. It also holds `sources` and the acronym-safe `label`, moved from `ticker.py`.

Done in Phase 0
- The news summary route and the local loader use `upsert_artifact_summary` instead of inserting (#62).

Done in #56
1. Every writer records through `record`: both analysis worker paths, the summary repair operation, the two `/llm/summarise` routes, the news summary service (and through it `/news/summarise` and Marketaux inline mode) and the local loader. `store_artifact_analysis` records inside its own locked transaction, so only its sentiment insert can still race, and its retry stays for that row. The other writers commit right after recording. `summary_metadata.py`, `stage_artifact_summary`, `upsert_artifact_summary` and the four "combine into text" functions are deleted. `Artifact` now declares its `summaries` relationship instead of getting it as a backref.
2. The team decided to delete `POST /artifact-summaries/`, with `create_artifact_summary` and `ArtifactSummaryCreate`. The two GET routes stay.
3. `needs_summary` replaces the four "is it summarised?" rules: in the admin ticker route, the news loop, Marketaux inline mode and its analysis queueing, and the local loader's duplicate path. The admin ticker route and the news loop decide which artifacts need a summary before their first commit, because a commit expires the summary rows `WITH_SUMMARY` loaded. The repair operation keeps today's selection, as the team decided: analysed announcements whose summary row is incomplete. It checks each new summary with `is_complete` before recording it, and no longer rewrites the artifact's raw text. An announcement removed while the model answers is listed under `failed` as no longer available.
4. The readers use the views. `/announcements` and `/tickers/symbol/{s}/news-feed` build each item from the artifact card. The brief story and clarity use `brief` and `clarity`, the deep-dive detail is the summary's text, and the notification worker quotes `alert_text`. The deep dive loads summaries with `WITH_SUMMARY` instead of one query per artifact, which was 10 step 5.
5. The team decided a missing summary shows as null everywhere, never as placeholder or raw text. The frontend's two copies of the backend's placeholder sentences, in `recordPresentation.meaningfulText` and `companyFormat.hasResearchText`, are deleted. Raw text stays visible only as source evidence (`sources[].evidence_text`).
6. The team decided not to wait for the claim-traceability branches. Whichever one is chosen adds its field through `SummaryExtension` and the artifact card.

Tests
- `test_artifact_summary.py` records and reads on Postgres. Like `SessionLocal`, its session does not autoflush. It checks one row after two records, stale lines and lists removed, nothing left after a rolled-back savepoint, the caller's unflushed metadata kept (this fails if `record` stops flushing), an empty summary refused, two concurrent first records, the extension hook, completeness, the repair selection and the views. Pure tests cover cleaning and legacy recovery. It replaces `test_summary_metadata.py`, whose storage test was a MagicMock whose `side_effect` depended on call order.
- `test_summary_writers.py` runs every writer against one scripted answer per summary kind. Each must give the same read back from one row, model and prompt version included. It also runs the repair operation through the analysis handler, including an announcement removed while the model answers. It checks that the local loader stores sentiment but no summary for an answer with no text. The worker's document path is checked in `test_pipeline_stages.py`. Neither file's session autoflushes.
- `test_artifact_card.py` covers tags, source names, link labels, link fallbacks, legacy rows, and an unsummarised artifact showing no lines or raw text. `test_announcements.py` and the new `test_ticker_routes.py` read the market feed and the ticker brief, news feed and deep dive on Postgres, with and without a summary. `test_notify_database.py` checks the alert email quotes the summary. `test_llm_routes.py` adds the regression test for re-summarising news. It also checks that the ticker route lists an answer with no text as that artifact's error and goes on to the next artifact. `test_news_summary_database.py` checks the same for the news loop.
- These replace the MagicMock news-feed, clarity and summary-metadata tests in `test_apis.py` (the old lines 34-156 and 481-586), the four mapping tests in `test_announcements.py`, the `_summary_values` and repair-dispatch tests in `test_document_workers.py`, and two tests in `test_news_summary.py`. The frontend tests check null instead of the placeholder sentences.

Behaviour changes
- Recording replaces the whole summary. A line, list or extension the new summary lacks is removed from `artifact_metadata`, where the old value used to stay.
- An answer with no text line is not recorded, where the admin, news and loader writers stored the title. `/llm/summarise/artifact/{id}` answers 502, and the ticker route and the news loops list it as that artifact's error. The worker and the local loader still store sentiment without a summary.
- No summary code commits any more. `ON CONFLICT` absorbs a concurrent first write instead of rolling back the session, and concurrent writers can no longer overwrite each other's metadata JSON.
- The local loader stores the prompt version and both clarity lists.
- `/llm/summarise/ticker/{symbol}` stops summarising news that has four lines. It now summarises again an announcement that has `about` and both clarity lists but lacks the summary, changed or matters line, which the old rule skipped. It does this on every call while the model leaves that line empty. The news loop, Marketaux inline mode and its analysis queueing act on news missing any of the four lines, not only `about`. The local loader summarises a duplicate again when it lacks the summary line or the clarity lists.
- With no summary, the market feed, ticker feed, brief story and deep-dive detail return null. They used to return placeholder sentences, a raw-text preview or the "is tracked from the StonksInHand database" sentence. `AnnouncementResponse.source_name`, `about`, `changed` and `matters` are nullable.
- The ticker feed now follows the market feed's card. It gets the same source names (ASX, Reddit, the publisher or provider), the Reddit link label, and the `source_url` then `pdf_url` link fallback. A record with no publisher reads "View original source". An untitled ticker-feed item is "Untitled ...". With no category, the tag comes from the artifact type ("News Article", not "News"). Market feed tags now keep all-caps words whole, as the ticker feed's already did.
- A legacy row whose joined text does not split into four parts shows as the summary line. The `what_its_about`, `what_it_is_about`, `what_changed` and `why_it_matters` keys, which nothing writes, are no longer read.
- Alert emails and the deep-dive detail now use the summary's lines. Both used the row's `summary_text` before. For consistent records and legacy rows the text is the same as before. Where the two stores disagree, as the old upsert race could leave them, both show the metadata lines rather than the row's text.
- `POST /artifact-summaries/` is removed.
- The frontend no longer hides the old placeholder sentences, so it must ship with this backend, not before it. Rolling the backend back to an image from before 07 needs the frontend rolled back too. The old backend sends "Summary pending.", "No change summary available yet.", "No detail available yet." and the "is tracked from the StonksInHand database" sentence. The new frontend would show them as text, for example under "AI-assisted brief".

Left over
- The two stores stay for now, as the team decided (the old step 5). Look again after 10 steps 3 and 4. Until then, `category_sentiment.py` reads the top-level keys for its keyword search and `_artifact_summary_text`, and the watchlist page reads `artifact_metadata.about` from `GET /artifacts/ticker/{id}`. `/artifacts` and `/artifact-summaries` still return the stores raw. If the stores are collapsed, make the summary row the one store.
- Serving the watchlist brief from the `brief` view (the old step 4) is now 10 step 4, through the watchlist summary endpoint.
- The repair operation still skips announcements with no summary row, as the team decided. `/llm/summarise/ticker/{symbol}` fills those gaps.
- If the model keeps leaving a line empty for some announcements, the ticker route spends an LLM call on each of them on every run. If that shows up in the LLM budget, the team can bring back the old skip rule for announcements in that route.
- `feature/86d4a0a1d-specific_report_sources` is not merged. Its change to `ticker._source_from_values` now belongs in `artifact_card.sources`. The claim-traceability branches (#68 and `feature/86d48cxxz-advanced_traceability`) are not merged either. The chosen one adds `SummaryExtension("claim_evidence", ...)`, required for announcements, to `EXTENSIONS`. It also keeps `claim_evidence` in `AnnouncementSummary.parse`, bumps the prompt version, and adds its field to the card and the clarity view.
- `tools/reclassify_artifacts.py` and the local loader's duplicate path still read the whole metadata JSON and write it back without a lock, so they can overwrite summary keys recorded at the same moment.
- `record` holds the artifact row lock until the caller commits, so loops commit after each artifact. 08 builds its persistence on `record`.
- After deploying, check on staging:
  - Run one analysis. Its summary row has `model_used` and `prompt_version`, and its metadata has all six keys.
  - `uq_artifact_summaries_artifact` exists. `ON CONFLICT` needs it.
  - A dry-run repair gives the same `missing_before` before and after the deploy.
  - The market feed, home page, source library, research summary and deep dive show the empty-summary states.
  - The Brevo alert smoke test passes.

Where the code is: `backend/app/services/artifact_summary.py`, `backend/app/services/artifact_card.py`, `backend/app/crud/artifact.py` (`store_artifact_analysis`), `backend/app/crud/announcement.py`, `backend/app/api/routes/ticker.py`, `backend/app/api/routes/llm.py`, `backend/app/services/news_summary.py`, `backend/app/services/marketaux.py`, `backend/parsing/analysis.py`, `backend/parsing/storage.py`, `backend/lambdas/analysis.py` (`_resummarise_missing_fields`), `backend/lambdas/notify.py` (`_load_context`), `frontend/src/app/components/announcements/recordPresentation.js`, `frontend/src/app/components/company/companyFormat.js`, `backend/tests/test_artifact_summary.py`, `backend/tests/test_artifact_card.py`, `backend/tests/test_summary_writers.py`, `backend/tests/test_ticker_routes.py`.

### 09 Category taxonomy ownership

Worth exploring, size S to M. Done in #56, except switching the category sentiment view to the proposed buckets, which is 10 step 3. Test approach: pure code.

What was wrong
- The classification engine itself is good, but adding a category meant editing 7 places: the taxonomy, `EXTRACTORS`, `CATEGORIES`, the storage `artifact_type` map, `_LEGACY_TO_STABLE`, the `ArtifactType` enum and the sentiment keywords.
- 4 of the 7 extractor classes returned `{}`.
- The documented legacy baseline silently ran rules-v2, so the recorded Macro F1 of 0.4765 could not be reproduced.

What was built

Each `CategoryDefinition` in `parsing/classification/taxonomy.py` owns its facts: its rules, the names it is stored under (`compatibility_category` and `artifact_type`), its display label, its metric extractor if it has one, and a proposed sentiment bucket. `category_definition()` and `artifact_type_for()` read them. `classify_document` did not change, so this stays in line with the classification implementation plan.

Done in #56
1. The real legacy keyword classifier, run from `dabaaf0` (the commit the baseline report names) over the 85 fixtures, reproduces the recorded baseline exactly. Its predictions are frozen in `tests/fixtures/classification/legacy_baseline.json`, and `evaluate_classification --classifier legacy-baseline` replays them. `current` is now the default. `parsing/classifier.py` and `--classifier legacy` are deleted.
2. The four extractor classes that returned `{}` and the `CATEGORIES` list are deleted.
3. Each definition has a label, an `artifact_type` and a proposed sentiment bucket. `parsing/extractors.py` and the local loader's `_CATEGORY_TO_ARTIFACT_TYPE` give way to the definitions. Adding a category now means one definition, plus an `ArtifactType` member if it needs its own stored type. The team decided the buckets are a proposal only, so the category sentiment view still buckets by keyword and no UI numbers change.
4. The proposed mapping below is handed to 10.

| Category | Proposed bucket |
|---|---|
| `quarterly_trading_update`, `guidance_update`, `half_year_results`, `full_year_results`, `annual_report` | revenue |
| `dividend_announcement`, `capital_management` | dividend |
| `corporate_action` | strategy |
| `leadership_change`, `governance_meeting` | organisational |
| `regulatory_legal` | risk |
| `security_notification`, `executive_transcript` | none proposed |

Bug found on the way: `Dockerfile.analysis` did not copy `parsing/classification/`, `parsing/extractors.py` or `parsing/classification_metadata.py`, so the analysis handler could not be imported in the deployed image. It had been so on `main` since the rules engine landed (`9816ef6`). Step 1 deletes a file that Dockerfile copied, which is how it came up. The image now copies them, and `test_lambda_images.py` checks that every image ships the backend modules its handler imports and copies no missing path.

Tests
- `test_classification.py` is unchanged, except that its one test of the deleted wrapper is removed.
- `test_category_taxonomy.py` checks every definition is complete, and pins every stored category name and artifact type.
- `test_classification_evaluator.py` checks the frozen baseline still gives the recorded Macro F1, unknown false-positive rate and per-category F1.

Behaviour changes: none from the taxonomy. Stored categories, artifact types and extracted data are unchanged, and the category sentiment view still buckets by keyword. The analysis image fix is a deploy change (see Left over).

Left over
- Deploy and check that the analysis Lambda starts. On the current staging stack, search the analysis function's CloudWatch logs for `No module named 'parsing.classification'` to see whether analysis has been failing since `9816ef6`.
- The API image ships only `app/`, so the category sentiment route cannot import the taxonomy. 10 step 3 needs one of two things: the analysis worker stores each artifact's bucket, or `Dockerfile.api` copies `parsing/classification` and `parsing/categories` (both pure Python).
- Today an artifact with no keyword match falls into "strategy". The proposal leaves security notifications and executive transcripts without a bucket. The team decided on 2026-10-13 that executive transcripts count in strategy and security notifications in no bucket (see decisions).
- Only the local loader stores a category's own `artifact_type`. The pipeline stores `asx_announcement_other` for every announcement (08).

Where the code is: `backend/parsing/classification/taxonomy.py`, `backend/parsing/categories/`, `backend/parsing/analysis.py` (`apply_rules`), `backend/parsing/storage.py`, `backend/tools/evaluate_classification.py`, `backend/tests/fixtures/classification/legacy_baseline.json`, `backend/tests/test_category_taxonomy.py`, `backend/tests/test_lambda_images.py`, `backend/Dockerfile.analysis`.

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
1. Pull a shared "analyse text" out of the three `analyse_*` functions. #56 already gives them one summary step (`_analysis_output` over `generation.generate`).
2. Merge the Lambda's two lifecycles. #56 already records both through `lambdas/pipeline_stage` (04) and reads documents through the raw document store (03).
3. Introduce the interfaces.
4. Point the admin routes (`/llm/...`), the Marketaux inline mode and the local loader at the module, or delete them in favour of queueing. Queueing the admin routes also removes the 30-second risk noted in 06.
5. At the next change to the message contract, rename `PublicDiscussionAnalysisMessage`, because it also carries news.

Tests
- Replace the event-order monkeypatch tests in `test_document_workers.py` (the stored-text analysis tests) with behaviour tests that use fakes at the interfaces. #56 already replaced the document one with a Postgres scenario in `test_pipeline_stages.py`.
- Fold `test_news_sentiment` and `test_news_summary` into them.

Where the code is: `backend/parsing/analysis.py:356-520`, `backend/lambdas/analysis.py:518-784`, `backend/parsing/storage.py:68-316`, `backend/app/services/news_sentiment.py:28-49`, `backend/app/services/news_summary.py`, `backend/app/services/marketaux.py:31-47,275-332`, `backend/app/api/routes/llm.py`.

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
3. The team agrees the mapping from taxonomy `primary_category` to bucket, because the numbers in the UI will change (see decisions). #56 records a proposed bucket on each category definition (see 09). Then replace the keyword matching. The API image cannot import the taxonomy today, so either store each artifact's bucket at analysis time or copy `parsing/classification` and `parsing/categories` into `Dockerfile.api`.
4. Add a watchlist summary endpoint. Delete the page's private `fetchJson` and the dead `{tickers: [...]}` branch in search.
5. Batch the deep-dive timeline's per-artifact summary query.
6. Optional: drop `"tone": "green"` from the deep-dive payload after `DeepDiveTimeline.jsx` hard-codes `styles.green`.

Tests
- Replace `test_apis.py:34-270`, which patches internals, with Postgres read-model tests plus a fake quote service. Follow the style of `test_database.py:908-963`.
- Replace the source-text assertions in `test_deployment_contracts.py:52-66` with a behaviour check: the API image cannot import `transformers`.

Where the code is: `backend/app/api/routes/ticker.py:20-597`, `backend/app/api/routes/category_sentiment.py`, `backend/app/crud/announcement.py:25-162`, `backend/app/api/routes/artifact.py:18-23`, `backend/app/crud/artifact.py:30-31`, `frontend/src/app/watchlist/page.jsx:21-137,244`, `frontend/src/app/search/page.jsx:36-46`, `frontend/src/app/components/ticker/DeepDiveTimeline.jsx`.

## Alerts track

### 13 Email sender port

Strong, size S to M. Done in #56. Unblocks 12 and 14. Test approach: a third-party service (Brevo behind a port, with a dry-run sender and a recording fake).

What was wrong
- The email provider had no real seam, so the notify worker and the preferences route each interpreted Brevo failures themselves, and they did it differently. Notify decided whether a `ValueError` meant a bad recipient by looking for the word "recipient" in its message.
- The route mapped every `ValueError` to 500, configuration and recipient errors alike, and every Brevo refusal to 502 "The verification service is unavailable". Stored subscription emails pass the same `email_validator` rules, so the recipient 500 was effectively unreachable. The reachable defect was a Brevo 400, 404 or 422, where Brevo refuses the address, answering 502 and so telling the investor to retry.
- Dry-run knowledge was split between modules. `settings.NOTIFICATIONS_DRY_RUN` was read three times in `brevo_alerts` (once in `_api_base_url`, twice in `send_email`) and twice in notify's `_send_alert`, which also owned the one-second send pacing.
- The SES to Brevo swap (`c244ab7`) touched 36 files, 26 of them outside tests.

What was built

The email sender in `backend/app/services/email_sender.py` is the one way the product sends email. A caller hands a sender an `OutgoingEmail`: the recipient, subject, HTML and text bodies, and an optional unsubscribe link that becomes `List-Unsubscribe` only. `send` answers one of four outcomes and never raises for a provider, network or configuration problem. The outcomes are `Accepted(message_id)`, `RecipientRejected(code, detail)`, `Unavailable(code)` (a retry may succeed) and `Misconfigured(code)` (our settings or the email need a fix). `check_message` makes the checks every sender makes first: exactly one mailbox with no display name, a one-line subject, and an absolute unsubscribe link, which must be HTTPS for a real send. `mailbox` and `web_link` are the shared address and link checks, and the Brevo adapter reuses them for its own settings.

Three adapters sit behind it. `BrevoEmailSender` (in `brevo_alerts.py`) posts to Brevo's transactional API. It takes an optional httpx client and an optional `SendPacer`, and it keeps none of Brevo's message text. `DryRunEmailSender` only logs, and answers a `dry-run-` id that is a digest of the email, so a replay gets the same id. `RecordingEmailSender` keeps each email for tests and answers scripted outcomes. `configured_sender(paced=False)` returns the dry-run sender when `NOTIFICATIONS_DRY_RUN` is set and Brevo otherwise, and it is now the only code that reads that switch. With `paced=True` the sender shares the module-level `ALERT_PACER` (one second). `current_sender` is the FastAPI dependency.

The Brevo adapter answers:
- When the email fails `check_message`: `RecipientRejected("invalid_recipient")`, or `Misconfigured("invalid_notification_configuration")` for a bad subject or unsubscribe link.
- When the API key or sender address is empty, or the base URL is HTTP: `Misconfigured("brevo_configuration_error")`.
- When the sender address, sender name or base URL is malformed (including a link `urlsplit` cannot parse): `Misconfigured("invalid_notification_configuration")`.
- Brevo 400, 404 or 422: `RecipientRejected` with Brevo's code. 408, 429 or 5xx: `Unavailable` with the code. Any other refusal, such as 401, 402 or 403: `Misconfigured` with the code.
- A transport error: `Unavailable("brevo_transport_error")`. A success without a message id, or any other error during the request: `Unavailable("brevo_send_failed")`.

Each caller decides what an outcome means. Notify records `Accepted` as sent and `RecipientRejected` as rejected (final). It records `Unavailable` or `Misconfigured` as failed and retries through SQS, storing the same codes as before. The preferences routes mark verification failed for every outcome other than `Accepted`, then answer 422, 502 or 500.

Done in #56
1. The port, its outcomes, `check_message`, `SendPacer`, the dry-run and recording senders, and `BrevoEmailSender`.
2. Notify sends through `configured_sender(paced=True)` and maps the outcome in `_send_rendered`. `_send_alert`, its lock and its pacing globals are gone.
3. `PUT /notifications/preferences` and `POST /notifications/preferences/resend-verification` get the sender from `Depends(current_sender)`. `_send_verification_email` maps the outcome through one table, `_UNSENT_VERIFICATION`, and logs only the outcome type and code, never the address. The callers' undo, which marks verification failed, is unchanged.
4. `brevo_alerts.send_email` is deleted, along with `BrevoApiError`, `BrevoAlertConfigurationError`, `_safe_header`, `_safe_url`, `_mailbox`, `_api_base_url` and `_dry_run_message_id`. `DRY_RUN_SENDER` moved to `email_sender.py`.
5. Review fixes:
   - The Brevo base URL now goes through the same `web_link` check as the unsubscribe link, and the adapter checks its settings in the same order the deleted `send_email` did. A malformed base URL therefore stores `invalid_notification_configuration`, as it did before.
   - A link `urlsplit` cannot parse, such as one with an unclosed `[`, now counts as malformed. Before this fix the sender raised, so notify left the ledger row claimed with no code, and the PUT answered an unhandled 500 and left verification pending.
   - The delivery scenarios now check that notify asks for the paced sender.

Behaviour changes
- A verification email Brevo refuses (400, 404 or 422) now answers 422 "The email service refused this address. Check the email address on your account." instead of 502 (see [Decisions still needed](#decisions-still-needed)). An invalid recipient answers 422 instead of 500, though stored addresses make that case effectively unreachable.
- A Brevo 401, 402 or 403 on a verification email answers 500 "Email verification is not configured" instead of 502.
- An unexpected error while the Brevo adapter makes its request now answers 502 on the preferences routes, with verification marked failed, instead of an unhandled 500. Notify still records it as failed with `brevo_send_failed` and retries.
- Notify's ledger statuses, error codes and retry decisions do not change.
- Live alert sends stay at least one second apart within one Lambda container (see [Decisions still needed](#decisions-still-needed)). A dry run is never paced. Containers do not share the pacer, and the template no longer sets reserved concurrency (`test_deployment_contracts.py:163`), so this is not a global rate limit.

Tests
- `test_email_sender.py` (pure) covers the recording sender and `check_message`, including links `urlsplit` rejects and HTTPS only when required. It also covers stable dry-run ids, `SendPacer`, and `configured_sender` following the dry-run switch, with `paced=True` sharing `ALERT_PACER`.
- `test_brevo_alerts.py` is now the Brevo adapter test. It gives the adapter an `httpx.MockTransport` client, so nothing is patched. It covers the payload and the `List-Unsubscribe` header, each refusal class without Brevo's message text, a transport error, and a success without a message id. It also covers the settings and email checks made before any request, including empty, schemeless, angle-bracketed, multi-line and unparseable base URLs, and pacing.
- `test_alert_delivery.py` drives `notify.handler` on Postgres, with savepoint sessions and the recording fake. It checks each outcome against the ledger row, the subscription mirror and `batchItemFailures`. It also covers a retried record sending exactly one alert, a dry run, a malformed Brevo base URL with the real sender, and notify asking for the paced sender.
- `test_alert_subscriptions.py` calls the routes through `TestClient(main.app)` on Postgres. Enabling alerts emails a link that verifies the address. An unsent email answers 422, 502 or 500 by outcome, with verification failed. A refused resend answers 422, and a malformed Brevo base URL with the real sender answers 500.
- `test_notify_database.py` uses the recording fake instead of patching `brevo_alerts.send_email`. `test_notify.py::test_runtime_configuration_load_precedes_configured_imports` now anchors on the `email_sender` import (17 deletes it later).
- Deleted:
  - the eight `send_email` tests in `test_brevo_alerts.py` and their transport fixtures;
  - in `test_notify.py`, `test_brevo_success_marks_the_delivery_sent`, `test_terminal_brevo_rejection_is_recorded_and_acknowledged`, `test_retryable_brevo_throttle_is_recorded_before_batch_retry` and `test_live_send_limiter_spaces_fanout_calls`, with the `_brevo_error` helper;
  - `test_alerts.py::test_terminal_brevo_error_updates_ledger_and_subscription`, with `_message_rejected`;
  - `test_notification_preferences.py::test_verification_email_contains_current_signed_app_link`.

Left over
- Real one-click unsubscribe stays optional and out of scope. Phase 0 stopped sending `List-Unsubscribe-Post` (#62). Real support would need an API-backed POST endpoint behind the `/api/*` CloudFront behaviour, added to the public allowlist in `test_access_policy.py`.
- A global send limit needs Brevo's real send-rate limit for the account first.
- Not checked locally: one real verification email and one real alert through Brevo on staging. That needs the Brevo key in SSM, a verified `ALERT_SENDER_EMAIL`, `NotificationsEnabled=true` and a deploy. Check that both emails link to the custom domain and that verification and unsubscribe work from a real inbox.

Where the code is: `backend/app/services/email_sender.py`, `backend/app/services/brevo_alerts.py:94-171` (`BrevoEmailSender`), `backend/lambdas/notify.py:507-538` (`_send_rendered`), `backend/app/api/routes/notification_preferences.py:65-81` (`_UNSENT_VERIFICATION`) and `:172-206` (`_send_verification_email`).

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

Strong, size M. Done in #56. Unblocks 18, and 17's secrets registry builds on its `gated_secrets()`. Test approach: a service we own. Every AWS read goes through an `Aws` port that tests replace with a fake account that records each call, and `apply --dry-run` prints the deploy without calling AWS.

What was wrong
- `deploy-staging.yml` wrote each switch and limit 7 to 8 times: the dispatch input (whose default copied the template default), the AUTO_* and MANUAL_* mappings, the dispatch and push assignments, the validation, the GITHUB_ENV export and the `sam deploy` override. The push path's fallbacks copied the template defaults again.
- The function-to-ECR map was repeated in the deploy workflow, the rollback workflow and three `infra/README.md` copies. Since #59 the rollback no longer listed parameters, but it still repeated the 7-function map. The README copies mapped only 6 of the 7 image functions, so SAM would refuse them, and they left out 11 parameters.
- The `describe-stacks … Outputs` query appeared 21 times: 16 in workflows (deploy-staging 7, publish-staging-frontend 5, execute-staging-change-set 2, rollback-staging-frontend 2) and 5 in `infra/README.md`, one of them reading the OIDC stack. The workflows also read stack Parameters 4 times and StackStatus once.
- A bad value (a limit out of range, a malformed email, a broken Rule) failed only at CreateChangeSet, after the images were built. Only the AuthProvider and true/false checks ran early. The Brevo and Marketaux secret checks were two hand-written bash preflights.
- A brand-new stack could not be planned unless `vars.SITE_DOMAIN_NAME` was set, and the push path failed again at "Capture the previous release". `FrontendBaseUrl` cannot be worked out in the template: ApiFunction would refer to FrontendDistribution, whose API origin refers to ServerlessHttpApi, whose routes refer back to ApiFunction.
- A manual change set reset every switch nobody chose to its template default, for example AuthProvider back to legacy. #59 had fixed the same silent reset in the rollback.
- The schema-drift script had three copies. `validate-branch.yml` and `validate-staging-release.yml` dropped `artifacts.is_duplicate` and `artifact_summaries.prompt_version`. `deploy-staging.yml` dropped only `is_duplicate`, because `a7dd2c6` missed it.

What was built

The release module, `backend/tools/release.py`, run as `python -m tools.release` from `backend/`. It is the only place that knows how a deploy is put together. `plan` writes a release plan: a value for every template parameter, taken from `--set`, then `--set-unless-empty` (where an empty value or `keep` means not given), then the live stack, then the template default. A parameter with no value anywhere is refused. The image parameters always point at the release SHA in this account's ECR repositories, and a release works out `FrontendBaseUrl`. Before any image is built, the plan checks every value against the template's constraints and Rules, checks that each gated secret whose switch is on exists as a SecureString, and checks that the template fits SAM's 51,200-byte inline limit once `sam deploy` packages it. SAM checks the packaged file, not the source: it adds `Metadata: SamResourceId` to every resource and writes the template out again without comments. `packaged_template()` writes the same text with PyYAML, byte for byte what SAM CLI 1.165.0 writes: 46,146 bytes today, from a 42,009-byte source. The plan prints a table of each value, its source and what it replaces to the log and the job summary, and the workflows read its registry and previous release SHA from the step outputs. `apply` checks that the template is unchanged, that the stack is as the plan found it and that the release images exist. It then runs the one `sam deploy` command the plan describes, or only prints it with `--dry-run`. A rollback is a plan that keeps every live value and swaps only the images. `outputs` and `previous-release` read the stack with one call each. A new stack is only created, and a live custom domain only removed, through a reviewed change set, so `--execute` refuses both. `AwsCli` is the real adapter behind the `Aws` port. The module needs only PyYAML, so the queue-wiring CI job runs its tests.

The template model (15) answers what the plan checks against: `Parameter.problems(value)`, `parameter_definitions()`, `rule_failures(values)`, `Function.image_parameter`, `image_parameters()` and `gated_secrets()`.

Done in Phase 0 (#59)
- The rollback workflow reads the live stack's parameters, changes only the three image URIs, and maps NotificationFunction.
- `FrontendBaseUrl` uses `https://$SITE_DOMAIN_NAME` when `vars.SITE_DOMAIN_NAME` is set.

Done in #56
1. The template model gives each parameter its default and constraints, and evaluates the Rules. It understands Fn::Equals, Fn::Not, Fn::And, Fn::Or, Ref and Condition, and raises on anything else, so a new kind of rule cannot pass unchecked. It names the ImageUri parameter of each image function, and lists the SSM secrets a function reads only while a true/false switch is on. A secret behind any other condition raises.
2. The release module, with `plan`, `apply` and `outputs`. Every override is double-quoted, because SAM CLI refuses `Key=` and cuts an unquoted value at a space. The queue-wiring CI job also runs `test_template_model.py` and `test_release.py`.
3. "Prepare staging backend rollback" runs `plan --rollback --no-execute`, then `apply`. It installs Python and PyYAML. The SHA check and the old-image check move into the module.
4. "Deploy staging release" plans straight after AWS sign-in, before the image builds, and applies after them. The ECR login, image tags and artifact names read the plan's registry and `RELEASE_SHA`. The health-check rollback reads the plan's `previous_release_sha`, and the frontend configuration comes from `outputs`. The bash resolution, both preflights, "Verify all release images exist" and "Capture the previous release" are gone. `sync_tickers.py` drops the push-path ticker fallback.
5. "Execute approved staging change set" reads the previous release with `previous-release` and the API endpoint with `outputs`. Its stack status check and the output table it keeps as evidence stay in bash.
6. `backend/scripts/reproduce_deployed_schema_drift.py` replaces the three inline copies. It creates the Supabase roles, upgrades to `86d2cognitoidentity`, drops both columns and upgrades to head.
7. `infra/README.md` plans and applies through the module. The first change set uses `--no-execute` and `--no-execution-role`, because §10 creates the execution role later. Enabling the schedule keeps every other live value except `FrontendBaseUrl`, which follows the site address, and the image URIs, which follow `--release-sha`. The stop procedure reads the live release with `previous-release`. Stack outputs come from `outputs --shell`. §10 documents `SITE_DOMAIN_NAME`, `SITE_CERTIFICATE_ARN` and `SITE_HOSTED_ZONE_ID`, and what removing `ALERT_SENDER_EMAIL` or `SITE_DOMAIN_NAME` does. `deployment.md` says to leave notifications off instead of naming the old input, and `devops-processes.md` is marked historical.
8. The team decided a manual deploy keeps live values. Every choice input lists `keep` first, and all 11 inputs default to it, so a change set changes only what someone chose. The inputs stay choice or string types, because a boolean false would fall through `inputs.x || vars.X` to the variable. This removed the last ticker copy in `deploy-staging.yml`.
9. Review fixes. The inline size check measures the packaged template. `--execute` refuses to empty a live `SiteDomainName`. `apply` reads the stack again and refuses one that changed after the plan. The guide's §9 names the values a release changes besides the ones given.

Tests
- `test_release.py` drives the module against the fake account. `test_release_dry_run_prints_one_complete_sam_deploy_command` runs `plan` then `apply --dry-run` and splits the printed command. It checks that the command maps exactly the template's image functions to their repositories, passes every parameter once, tags the images with the SHA and sets the role. It also checks that `--no-execute-changeset` appears only for a change set, and that the dry run neither calls AWS nor runs sam. Other tests cover:
  - the resolution order, `keep` and empty values, and unknown and repeated keys;
  - constraints and Rules;
  - the four `FrontendBaseUrl` cases;
  - a new or REVIEW_IN_PROGRESS stack, and removing the custom domain;
  - the previous release, gated secrets and rollbacks;
  - `apply`'s checks: a changed template, a stack that changed, appeared or disappeared after the plan, and a missing image;
  - `outputs`, `IMAGE_REPOSITORIES` against `bootstrap.yaml` and the template, and `AwsCli` with a fake runner.
  For the inline limit, an inline template packages to exactly SAM CLI 1.165.0's output and the checked-in template fits. A template whose source fits but whose packaged form is one byte over is refused, and one at the limit passes.
- `test_template_model.py` covers parameters, Rules, image parameters and gated secrets on an inline template and on the checked-in one.
- `test_deployment_contracts.py` checks the workflows as PyYAML rules instead of text. No workflow step builds a `sam deploy`. `describe-stacks` appears only in the two frontend workflows and two kept execute steps. The deploy plans before the builds, applies after them, then checks health, then triggers the rollback with the plan's `previous_release_sha`. A manual run only creates a change set, and every manual input defaults to `keep` and reaches the plan through `--set-unless-empty`. The rollback plans, then applies. The three CI jobs reproduce the schema drift through the script, and the staging guide holds no `sam deploy` command or image map.
- These replace `test_staging_workflow_wires_brevo_notification_parameters`, `test_approved_main_merges_deploy_backend_and_frontend_automatically`, `test_release_workflows_keep_public_discussion_schedule_explicit`, `test_release_workflows_map_every_image_function_to_a_repository`, `test_deploy_supplies_every_parameter_without_a_default`, `test_rollback_keeps_live_parameters_and_swaps_only_images`, `test_deploy_links_emails_to_the_custom_domain_when_configured` and the workflow half of `test_marketaux_is_ssm_backed_bounded_and_release_gated`.
- The drift script has no unit test, because it needs an empty Postgres server. CI runs it in three jobs, and it was run once against a throwaway `postgres:16-alpine`.

Behaviour changes
- Every template parameter is passed. AlertDailyBudget and AlertMaxPerInvestorPerRun used to keep their value through SAM's UsePreviousValue. They now go in with their live value, so nothing changes in effect.
- The plan reads the stack before the image builds. The old workflow read the previous release right before `sam deploy`, and SAM read the two alert limits when it created the change set. `apply` reads the stack again and refuses if it changed in between, for example because a change set was executed while the images built.
- A failed `describe-stacks` now stops the plan. The old push path ran it with `2>/dev/null || true`, so a transient AWS error silently reset each switch to its template default, for example AuthProvider to legacy.
- A bad value or a failed Rule stops the run in the plan step, before the image builds, instead of at CreateChangeSet.
- The secret check covers every gated secret in the template, and runs whenever its switch resolves to on, including a kept live value. Today that is still Brevo and Marketaux.
- A manual deploy keeps the live value of every input left at `keep`, where it used to reset each one to the template default.
- SAM now accepts an empty value, because every value is quoted. The old workflow passed the five environment variables to SAM unquoted, so an unset one failed the deploy. Now an unset `ALERT_SENDER_EMAIL`, `SITE_CERTIFICATE_ARN` or `SITE_HOSTED_ZONE_ID` clears that parameter, and the Rules refuse that while notifications or the custom domain need it. An unset `SITE_DOMAIN_NAME` would remove the custom domain, so a push refuses it, and only a manual run's reviewed change set can remove it. An unset `OPERATIONS_EMAIL` still fails, now in the plan.
- A brand-new stack can be created through a reviewed change set without `vars.SITE_DOMAIN_NAME`. `FrontendBaseUrl` stays `https://example.invalid` with a warning until the next release, and the plan refuses notifications on. A push refuses to create a stack, with a clear message. A REVIEW_IN_PROGRESS stack counts as new, as it does in SAM.
- Every release and rollback writes its parameter table to the job summary.
- The rollback workflow installs Python and PyYAML. An empty live value is now passed quoted, where the jq version passed `Key=`, which SAM CLI refuses.
- The deploy job's schema-drift check also drops `artifact_summaries.prompt_version`, as the two validation jobs already did.
- The `infra/README.md` commands map all 7 image functions and pass every parameter. The guide's first change set takes the template default for every value it does not set.

Left over
- Staging checks that need AWS and GitHub Actions:
  - Run the #59 "Prepare staging backend rollback" once and check that only the three image URIs change. Then run the module's version and compare. The #59 version passes each live value unquoted, so SAM refuses it if any live value is empty (AlertSenderEmail or a `SITE_*` value). In that case, compare only the module's run with the live stack.
  - Run "Deploy staging release" by hand (it only creates a change set) with every input at `keep`, and compare the summary table with the live stack.
  - The first push to `main` then exercises `plan --execute`, `apply`, the health check and the rollback trigger.
  These runs also confirm that SAM accepts the generated command and that `stocks-in-hand-github-staging` covers the module's reads.
- `publish-staging-frontend.yml` and `rollback-staging-frontend.yml` keep their 7 output queries in bash. The first checks out the release SHA, which may be older than the module, and the second checks out nothing. The team decided to leave them for now.
- The change-set export still picks the newest CREATE_COMPLETE change set. When sam finds no changes, it can export an older, unexecuted one. The plan could record its time so the export can filter on it.
- The image builds and the "Detect existing immutable release images" loop still name the three ECR repositories in YAML. `apply` checks the images in the module's repositories, so a mismatch stops before `sam deploy`.
- `packaged_template()` matches SAM CLI 1.165.0's packaging, but `setup-sam` installs the newest SAM CLI. If a later version writes more, SAM could refuse a template the plan passed. Pinning the SAM CLI version in `setup-sam` would prevent that.
- `infra/samconfig.toml` is no longer read by any documented command. The module passes every option itself, and SAM CLI reads only the file's "default" section, which it does not have. Delete it, with its two path-filter lines, or keep it for hand-run `sam` commands.
- §10's read of the deploy role ARN from the OIDC stack stays a `describe-stacks` query, because `outputs` reads only the application template's outputs.
- The `github-oidc.yaml` text checks, the CI lint and the deploy role work belong to 18. Its role rule tests can check the roles against `CLOUDFORMATION_ROLE_NAME`, `IMAGE_REPOSITORIES` and `gated_secrets()`.

Where the code is: `backend/tools/release.py`, `backend/tools/template_model.py`, `backend/tools/sync_tickers.py`, `backend/scripts/reproduce_deployed_schema_drift.py`, `.github/workflows/deploy-staging.yml`, `.github/workflows/prepare-staging-backend-rollback.yml`, `.github/workflows/execute-staging-change-set.yml`, `.github/workflows/validate-branch.yml`, `.github/workflows/validate-staging-release.yml`, `.github/workflows/ci-infra-queue-wiring.yml`, `infra/README.md`, `deployment.md`, `devops-processes.md`, `backend/tests/test_release.py`, `backend/tests/test_template_model.py`, `backend/tests/test_deployment_contracts.py`.

### 17 Runtime configuration

Worth exploring, size M to L. Needs 15. Test approach: a service we own (SSM behind an interface).

What is wrong
- `Settings` is built when `app.core.config` is first imported, so SSM secrets must be loaded before anything imports it. Only comments state that rule, and `test_notify.py:846-856` enforces it by comparing where lines sit in the source file.
- The Lambdas skip `Settings` and read the environment again with their own defaults. (The source-URL override that applied to manual scrapes but not scheduled ones is gone in #56.)

What to build

One configuration module that is built the first time it is used. It declares every setting once, with its limits, and resolves `*_PARAMETER` secrets itself. A secrets registry lists each secret, and the template model (15) checks that registry against the environment variables and IAM grants.

Done in Phase 0
- The 15 unread `Settings` fields and the stale `GROQ_API_KEY_PARAMETER` in `.env.example` are deleted (#65, #62). So is `ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED` (#62).
- The document size limits now come from `lambdas/download_validation.py`, and `MAX_ANALYSIS_CHARS` from `sentiment.sentiment_input` (#62).
- `BEDROCK_MAX_OUTPUT_TOKENS` is gone. Each summary kind sets its own output budget (06, #56).
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
| How to handle one-click unsubscribe | 13 | Decided for now: stop sending the header (#62). An API-backed endpoint is optional later and stays out of scope in #56. |
| What the preferences routes answer when the provider refuses a verification email's recipient | 13 | Decided in #56: 422, with a message to check the account email. Unavailable answers 502 and misconfigured 500, and verification is marked failed in every case. |
| Whether live alert sends stay one second apart per Lambda container | 13 | Decided in #56: keep it, through the module-level `ALERT_PACER`, which only alert fan-out uses. A dry run never paces. Brevo's real rate limit is still to be found. |
| Whether to keep the raw-token form of `POST /notifications/unsubscribe` and the one-time `unsubscribe_token` in the PUT response | 14 | Decided: keep both for now. |
| Mapping from taxonomy category to sentiment bucket, and whether one artifact may count in several buckets | 10 | Decided on 2026-10-13: 09's proposed table, with one bucket per classified announcement. Executive transcripts count in strategy. Security notifications (Appendix 2A, 3G and 3H) count in no bucket. News and unclassified announcements keep keyword matching. 10 step 3 makes the switch, so the UI numbers change then. Until then the view buckets by keyword: #62 fixed the matching, and 09 in #56 records the proposed bucket on each category definition. |
| What the latest filing signal on the brief and watchlist shows | 10 | Decided on 2026-10-13: the sentiment of the most recently published ASX announcement. Today it is the most recently analysed sentiment of any artifact stored against the ticker, which can be a news article. |
| Whether `source_url` on Queue A is authoritative | 04 | Decided in #56: the ticker catalogue is authoritative. The `{TICKER}_SOURCE_URL` override is removed and Queue A records the catalogue's page. |
| How to count a malformed public-discussion post: failure or duplicate | 05 | Decided in #56: a failure. It counts in `items_failed` and its run ends partial. |
| Which meaning `SUPPORTED_TICKERS` keeps, and what the other meaning is renamed to | 01 | Decided in #56: it means "enabled for manual scraping" (the `Settings` field and env var). The analysis worker's copy is gone; it accepts catalogue tickers directly. Revisit if the team wants a different name. |
| When to rename the `/gemini` routes | 06 | Decided in #56: now, to `/llm/...`, with no alias. The frontend never called them. |
| Whether to collapse the two summary stores after the views land | 07 | Decided for now in #56: keep both stores; the artifact summary module hides them. Look again after 10 steps 3 and 4. If they are collapsed, make the summary row the one store. |
| What a feed card, the brief story and the deep-dive detail show with no summary | 07 | Decided in #56: null everywhere, never placeholder or raw text. The frontend's placeholder lists are deleted. |
| Whether 07 waits for the claim-traceability branches | 07 | Decided in #56: no. The chosen branch adds its field through `SummaryExtension` and the artifact card. |
| Whether to delete `POST /artifact-summaries/` | 07 | Decided in #56: delete it, with its crud functions and `ArtifactSummaryCreate`. |
| Whether the summary repair also takes announcements with no summary row | 07 | Decided in #56: no, keep today's selection. |
| Whether a manual deploy keeps the live value of every input it does not choose | 16 | Decided in #56: yes, every dispatch input defaults to `keep`. |
| Whether the frontend publish and rollback workflows read stack outputs through the release module | 16 | Decided in #56: not for now; they stay in bash. |
| Whether a push may create a brand-new stack | 16 | Decided in #56: no; a new stack is only created through a reviewed change set. |
| Whether the deployment-test stack is still needed | 18 | Decided on 2026-10-13: no. Candidate 18 deletes the two deployment-test roles and their outputs. |
