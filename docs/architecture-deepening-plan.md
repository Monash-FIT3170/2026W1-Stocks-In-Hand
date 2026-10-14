# Architecture Deepening Plan

## In short

- This plan makes the parts of the code that change most often easier to change and easier to test. Those parts are the announcement pipeline, LLM analysis and summaries, the ticker API, investor alerts and deployment.
- The main idea is to take knowledge that is copied across many files and give it one home (a "module") with a small, clear interface. Tests then check that interface instead of private functions.
- The work is split into 18 pieces of work called candidates, grouped into phases. Phase 0 fixes live bugs and deletes dead code first, so the later work starts from a smaller and correct codebase.
- Phase 0 is done in #56. It was reviewed as PRs #57 to #65, which are being closed in favour of #56.
- All 18 candidates are done in #56 too: Phase 1 (01, 15 and 11), Phase 2 (04, 03, 02 and 05), Phase 3 (06, 07, 09 and 08), Phase 4 (10), the alerts track (13, 12 and 14) and the deploy track (16, 17 and 18). #56 is the one PR to merge. It passes 1174 backend tests with Postgres and LocalStack running, the same on Python 3.11 and 3.12.
- #56 adds four migrations: `86d9seedtickers`, `86d9statuschecks`, `86d9engagement` and `86d9artifacttypes`. No workflow runs them, so they are applied by hand, as `infra/README.md` §4 says. The first deploy also needs the hand checks listed in [Checks before and after merging #56](#checks-before-and-after-merging-56).
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

Where #56 leaves these points:
- Met: 1 (Phase 0), 3 (#61 and 04), 4 (06, 07 and 08), 6 (12, 13 and 14) and 7 (15, 16 and 18).
- Point 2 is close. Besides the catalogue entry and the source adapter, a new ticker needs its adapter name in `AdapterName`, a line in `ADAPTER_TYPES`, its recorded pages pinned in a test, and its own seed migration (see 01).
- Point 5 is met for access (11). The brief, news feed, deep dive, category sentiment and watchlist summary routes now only call a read-model (10), and each alert settings route makes one call (14). `POST /llm/categorise/recent` and `GET /reddit/ticker-sentiment/{t}` still generate inside their routes (see 08's Left over).
- Point 8 is mostly met. A few tests still patch a private seam: the queue modules' `_sqs_client`, `parsing.analysis._ocr_pdf` and `crud.scrape_run._lock_run`.

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
| 07 | Artifact summary | Phase 3 | Strong | M to L | 06 | Done in #56 (10 serves the watchlist brief) |
| 09 | Category taxonomy ownership | Phase 3 | Worth exploring | S to M | Phase 0 | Done in #56 (10 made the bucket switch) |
| 08 | Artifact analysis | Phase 3 | Strong | L | 03, 04, 06, 07 | Done in #56 |
| 10 | Ticker read-models | Phase 4 | Strong | M | 01, 07, 09 | Done in #56 (the bucket remap uses the decided mapping) |
| 13 | Email sender port | Alerts track | Strong | S to M | Phase 0 | Done in #56 |
| 12 | Alert delivery | Alerts track | Strong | M | 13 | Done in #56 |
| 14 | Alert subscription lifecycle | Alerts track | Worth exploring | M | 13 | Done in #56 |
| 16 | Release parameters | Deploy track | Strong | M | 15 | Done in #56 |
| 17 | Runtime configuration | Deploy track | Worth exploring | M to L | 15 | Done in #56 |
| 18 | OIDC role pair | Deploy track | Speculative | S to M | 16 | Done in #56 (the deployment-test roles are deleted) |

"Strong" means the problem is clear and the fix is worth doing. "Worth exploring" means it is probably worth doing but needs a closer look or a team decision first. "Speculative" means it may not be needed at all.

The alerts track and the deploy track do not depend on the ingestion or analysis phases, so they were done in parallel with them.

## Order of work

1. Merge #56. It is the one PR to merge. It holds this plan, Phase 0 (reviewed as PRs #57 to #65, which are being closed in its favour) and all 18 candidates: Phase 1 (01, 15 and 11), Phase 2 (04, 03, 02 and 05), Phase 3 (06, 07, 09 and 08), Phase 4 (10), the alerts track (13, 12 and 14) and the deploy track (16, 17 and 18). It passes 1174 backend tests with Postgres and LocalStack running, the same on Python 3.11 and 3.12. Without LocalStack, its one LocalStack test skips.
2. Apply its four migrations by hand before its first release: `86d9seedtickers` (Phase 0), `86d9statuschecks` (04), `86d9engagement` (05) and `86d9artifacttypes` (08). 10, 14 and 17 add none. No workflow runs them (`infra/README.md` §4), and the merge starts that first release, because a push to `main` deploys staging. A release deploys the backend before it publishes the frontend, which 07 and 10 need.
3. Do the checks in [Checks before and after merging #56](#checks-before-and-after-merging-56). They need staging, AWS or a GitHub Actions run, and some of them must come before the merge.

### Other open branches

These branches were written against `main` and do not build on #56. Each needs porting onto it, before or after it merges.

- #67 (`feature/announcement-monitor`) adds feed eligibility to `app/services/llm.py`, `lambdas/analysis.py` and `app/crud/announcement.py`. #56 replaced `llm.py` with `app/services/generation` (06), moved analysis into `lambdas/artifact_analysis.py` (08) and rebuilt the market feed on the artifact card (07). Its `_required_summary_values` also fails any analysis that has no summary, so with no LLM switched on every analysis fails again, which #58 fixed. Port it onto `generation` as a `FeedEligibility` kind.
- #68 (`feature/86d2ba6e6-claim_source_traceability`) and `feature/86d48cxxz-advanced_traceability` define `claim_evidence` in incompatible ways and no longer merge. Once the team picks one, rewrite it onto 07's `SummaryExtension` hook and the artifact card (see 07's Left over).
- `feature/86d4a0a1d-specific_report_sources` has no PR. Its backend change to `ticker._source_from_values` now belongs in `artifact_card.sources`. The `CitationLinks.jsx` it edits is now in `components/sources/`, and no page imports it (see 10's Left over).

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
- The "Queue wiring regression tests" CI job installs only pytest and PyYAML, and runs `test_queue_wiring.py`, `test_deployment_contracts.py`, `test_template_model.py`, `test_release.py` and `test_github_oidc.py`. Keep those five files, and anything they import, free of other dependencies. Today that means `backend/app/core/config.py` and what it loads (`backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/alert_vocabulary.py` and `backend/app/sources.py`), and `backend/tools/sync_tickers.py`, `backend/tools/template_model.py`, `backend/tools/verify_queue_wiring.py` and `backend/tools/release.py`. The configuration must need only the standard library: `test_queue_wiring.py` imports it with `python -S`, and fails if the job's path filters miss a module that import loads. A test file added to the job's pytest command must also go in both of its path filters, or `test_queue_ci_lints_every_template_and_runs_when_one_changes` fails.
- Every setting is declared once in `backend/app/core/config.py`, with its default and limits, and read through `settings` (17). No module in `app/`, `lambdas/`, `parsing/`, `scrapers/` or `alembic/`, nor `main.py` or `lambda_api.py`, may read `os.environ` or `os.getenv` outside `app/core/config.py`. `test_only_the_configuration_reads_the_environment` allows only facts AWS sets about the process: `AWS_LAMBDA_FUNCTION_NAME` in `app/database/connection.py`, and `AWS_LAMBDA_RUNTIME_API` and the environment Chromium inherits in `scrapers/browser.py`. A variable a function gets in `infra/template.yaml` must be a declared setting or name a registered secret, and a literal value must equal the declared default unless it is listed as a deliberate difference, or the rules in `test_queue_wiring.py` fail. Tests patch `settings` instead of setting an environment variable, though nothing checks that.
- `parsing/classification` and `parsing/categories` must use only the standard library, because `Dockerfile.api` ships them to the API (10). `test_lambda_images.py` fails on any other import, which CI's full install would otherwise hide.
- Line references in a "What was wrong" list point at the code before that candidate was done. The others point at #56, unless they say "old". If a line does not match, search for the function or symbol name instead.
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
- The repo had no `CONTEXT.md` and no ADRs when this plan was written. #56 adds `CONTEXT.md` with the first project terms, and the first ADR, `docs/adr/0001-remove-the-deployment-test-deploy-roles.md` (see 18).

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
| Appendix 3G/3H notices counted as "risk", because "securitynotification" contains "security". | #62 | Keywords match whole words only. A classified announcement now counts in one bucket, as decided on 2026-10-13 and done by 10 in #56. |
| The document size limit was 10 MiB in code and 25 MiB in the template. The DOCX limit was 50 MiB in code and 20 MiB in the template. | #62 | Both defaults live in `lambdas/download_validation.py` (`document_size_limit()`, `docx_uncompressed_limit()`) and match the template. 17 (#56) moved them into `app/core/config.py` as `MAX_DOCUMENT_BYTES` and `MAX_DOCX_UNCOMPRESSED_BYTES`, and a template rule keeps them equal to the template. |
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
| 15 unread `Settings` fields (14 in #65, `NOTIFICATION_QUEUE_URL` in #62), the stale `GROQ_API_KEY_PARAMETER` in `.env.example`, `SEED_TICKERS` in both compose files, and the `enqueue_public_discussion_analysis` alias. `NOTIFICATION_QUEUE_URL` was not really unread: the analysis worker read it with `os.getenv`, and 17 (#56) declares it again. | #65, #62 |

### Left over from Phase 0

These were found or deferred during Phase 0. Each one is also noted in the candidate it belongs to.

- `"tone": "green"` in the deep-dive payload was kept because `DeepDiveTimeline.jsx` used it to colour the timeline dot. #42 deleted that component, and `DeepDiveNotebook.jsx` does not read `tone`, so it could go with no frontend change. Done in #56: 10 dropped `tone`, `metrics` and `month`.
- `BaseScraper.download_pdf` is still used by `backend/scripts/populate_local_content.py` and still imports `lambdas.source_download` (candidate 02). Done in #56.
- `crud.artifact.get_bluesky_posts_for_ticker` and `get_mastodon_posts_for_ticker` became dead in #64 but were not on the list (candidate 05). Done in #56.
- `/headlines` and `/analyse` in `backend/main.py` were kept because they may still be used locally. `/analyse` now needs an admin session.
- If a Lambda times out on its final receive, its error handler never runs, so nothing records the final failure (candidate 04). Done in #56 with a sweep the schedule runs.
- With 4096 output tokens, an admin summary route could come close to the 30-second API Gateway limit (candidate 06). Done in #56 by 08 for the two summary routes, which now queue a summary request. `POST /llm/categorise/recent` and `GET /reddit/ticker-sentiment/{t}` still generate inline.
- Run "Prepare staging backend rollback" once against staging to check the #59 change. It only creates a change set. The only parameter changes should be the three image URIs (candidate 16). 16 replaces the #59 rollback with the release module in #56, so run the #59 version from its branch (`bugfix/release_workflow_parameters`) before #56 merges, then the module's version, and compare (see 16's Left over). Still open, and listed under [Checks before and after merging #56](#checks-before-and-after-merging-56).
- Deleting unread `Settings` fields meant a malformed `MAX_*` or `DISCOVERY_LOOKBACK_DAYS` value no longer crashed the API at import, while each Lambda that read them handled bad input its own way (candidate 17). Done in #56 by 17: every setting is declared once with its limits, and a bad value fails at the first settings read with `ConfigurationError`.

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
3. `_ensure_default_tickers` is removed from the read routes. Migration `86d9seedtickers` seeds the rows. It is applied by hand before a release, with the other migrations (`infra/README.md` §4).
4. The scraper registry maps adapters to scrapers and takes its ticker keys from the catalogue. The analysis worker builds its `OBJECT_KEY` pattern from the catalogue and checks identity with `adapter_matches_ticker`, so its own `SUPPORTED_TICKERS` set is gone.
5. `backend/tools/sync_tickers.py` rewrites the copies that cannot import Python: `frontend/src/app/ticker/tickers.json` (read by `generateStaticParams`), the CloudFront `tickerRoute` pattern and the `ScheduledTickers` default. Candidate 16 removed both `deploy-staging.yml` copies. The push fallback went with the bash resolution, and the manual input now defaults to `keep`. `test_ticker_list_copies_match_the_catalogue` fails when a copy is stale, and the queue-wiring CI job now runs on catalogue changes. The ApiFunction's `SUPPORTED_TICKERS` variable is removed because `Settings` already defaults to the catalogue.
6. The ticker list in `docker-compose-dev.yml` and the ticker and source-URL lines in `backend/.env.example` are removed.

To add an ASX ticker now: add a catalogue entry and its adapter name to `AdapterName` in `backend/app/sources.py`, write its source adapter (candidate 02) and add it to `ADAPTER_TYPES` in `backend/scrapers/registry.py`, record its pages with `python -m tools.record_source_pages <TICKER>` and pin them in `test_source_adapter_fixtures.py`, write a seed migration for the row, update `test_migration_seeds_the_catalogue_facts` to read it, and run `python -m tools.sync_tickers` in `backend/`.

Tests
- `test_ticker_catalogue.py`: normalisation, and Postgres tests for `ensure_ticker` (seeded row, catalogue facts, a repeat call, unknown symbol, placeholders filled and curated values kept).
- The text search in `test_deployment_contracts.py` is replaced by the sync check, and the AST check in `test_expanded_scraper_registry.py` by catalogue-wide scraper and object-key tests.
- The `_ensure_default_tickers` call-count tests in `test_apis.py` are deleted.

Left over
- Migration `86d9seedtickers` is a snapshot. A new ticker needs its own seed migration.

Where the code is: `backend/app/sources.py`, `backend/app/crud/ticker.py`, `backend/scrapers/registry.py`, `backend/lambdas/artifact_analysis.py` (the analysis worker's `adapter_matches_ticker` check), `backend/lambdas/raw_documents.py` (the object key pattern), `backend/lambdas/schedule.py`, `backend/tools/sync_tickers.py`, `frontend/src/app/ticker/tickers.json`.

### 15 Template model

Strong, size M. Done in #56. Unblocks 16 and 17. Test approach: pure code.

What was wrong
- The tests read `infra/template.yaml` in three different ways: 19 text slices that depended on resource order, a regex, and a YAML loader.
- They checked exact values that someone remembered to check, and some could never fail.
- The Notification queue was missing from the queue-wiring checks.
- Nothing stated that a queue's visibility timeout must be at least 6 times its consumer's timeout.

What was built

`backend/tools/template_model.py` parses the template once and answers questions about it: functions, the queue each function consumes, SendMessage targets (including grants under `!If`), environment variables, readable SSM parameter names, queue settings, dead-letter queues, the alarms watching a queue and the outputs that export it. Intrinsic functions keep CloudFormation's JSON form, so `!Ref` and `!GetAtt` can be told apart. It needs only PyYAML. 16 (#56) extends it with each parameter's default and constraints (`Parameter.problems`, `parameter_definitions`), the template's Rules (`rule_failures`), each image function's ImageUri parameter (`Function.image_parameter`, `image_parameters`) and the secrets a function reads only while a switch is on (`gated_secrets`). 18 (#56) adds the statements of an IAM role's inline policies (`TemplateModel.role_statements`, `Statement.covers`).

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
- 16 (#56) replaced the deploy and rollback workflow text checks in `test_deployment_contracts.py` with PyYAML rules. 18 (#56) replaced the `github-oidc.yaml` text checks, including the queue-attributes check in `test_queue_wiring.py`, with rule tests in `test_github_oidc.py`. `test_staging_validation_workflow_cannot_deploy` belongs to neither 16 nor 18.

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

Where the code is: `backend/app/services/scrape_runs.py`, `backend/lambdas/pipeline_stage.py`, `backend/lambdas/discovery.py`, `backend/lambdas/download.py`, `backend/lambdas/analysis.py`, `backend/lambdas/artifact_analysis_records.py` (analysis `start` and `finish`, which pick the transition by whether the download is stored, as `fail_abandoned_work` does), `backend/lambdas/schedule.py`, `backend/app/crud/scrape_run.py`, `backend/app/status.py`, `backend/alembic/versions/86d9statuschecks_check_pipeline_status_values.py`.

### 03 Raw document store and validated document

Strong, size M. Done in #56. Unblocks 08. Test approach: real LocalStack, plus an in-memory store for worker tests.

What was wrong
- The S3 key was split between two workers: the download worker wrote `raw/{ticker}/{artifact_id}/{sha256}.{ext}` and the analysis worker read it back with its own regex.
- Both workers marked the artifact as stored, each its own way.
- A `DownloadedDocument` did not prove it was validated, so it was validated again at four points, and `document_too_large` was raised in 7 places.

What was built

`validated_document` (in `lambdas/download_validation.py`) is the only way to build a `DownloadedDocument`; its checksum and content type are derived from the validated bytes. `lambdas/raw_documents.RawDocumentStore` owns, for both workers, the key layout and parsing (`locate`), the object metadata, "put only if absent", "is it still there", "read and verify" and "is this object the document its key names" (`verify`). It sits on an `ObjectBucket`: `S3Bucket` for AWS and LocalStack, `InMemoryBucket` for tests.

Done in Phase 0
- The size limits agree with the template and live in `lambdas/download_validation.py` (#62). 17 (#56) moved them into the runtime configuration.
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

Where the code is: `backend/lambdas/raw_documents.py`, `backend/lambdas/download_validation.py`, `backend/lambdas/download.py`, `backend/lambdas/artifact_analysis.py` (`analyse_stored_document`), `backend/tests/test_raw_documents.py`.

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
- Run the `86d9engagement` backfill a second time. The migration is applied by hand before the release (`infra/README.md` §4), but `main`'s collectors keep storing posts without an engagement until the new API image is live, and the new collector writes one only when it creates a post, never on a duplicate. `get_discussion_posts_for_ticker` puts such a post after every other, so it can drop out of the Reddit digest. Once the new image is live, run the backfill's UPDATE again with the migration database URL. From `backend/`, `python -c "import runpy; print(runpy.run_path('alembic/versions/86d9engagement_store_discussion_engagement.py')['BACKFILL'])"` prints it. It fills in only posts that have no engagement, so it can run twice. Do not run it again through alembic, as 08 does for `86d9artifacttypes`: this migration's downgrade removes every post's engagement. Do the same after any rollback of the API image, which the public discussion scheduler also runs.

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
- With 4,096 output tokens and up to two repair calls, an admin summary route could run past the 30-second API Gateway limit. Done in #56 by 08 for the two summary routes, which now queue a summary request. `POST /llm/categorise/recent` and `GET /reddit/ticker-sentiment/{t}` still generate inline, and tuning each kind's output budget from the Bedrock token logs would lower their risk.
- `news_summary.summarise_news_artifact` turned `Unavailable` back into `LLMUnavailableError`, because its callers counted it as a per-artifact error. Gone in #56: 08 deleted `app/services/news_summary.py` with `POST /news/summarise`.
- The local loader (`parsing/storage.py`) dropped the prompt version and the clarity lists when it stored a summary. 07 fixed this in #56, and 08 deleted `parsing/storage.py`. The loader now records summaries through the artifact analysis module.
- No prompt text changed, so no prompt version changed.

Where the code is: `backend/app/services/generation/` (`__init__.py`, `kinds.py`, `providers.py`, `bedrock.py`, `groq.py`), `backend/app/services/llm_errors.py`, `backend/app/sentiment_buckets.py`, `backend/app/api/routes/llm.py`, `backend/app/api/routes/reddit.py`, `backend/lambdas/artifact_analysis.py` (`_summary_request`, `summarise`), `backend/tests/test_generation.py`, `backend/tests/test_llm_routes.py`.

### 07 Artifact summary

Strong, size M to L. Done in #56. 10 serves the watchlist brief, also in #56. Unblocks 08 and 10. Test approach: real Postgres.

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
- `test_artifact_card.py` covers tags, source names, link labels, link fallbacks, legacy rows, and an unsummarised artifact showing no lines or raw text. `test_announcements.py` and the new `test_ticker_routes.py` (now `test_ticker_read_models.py`, which 10 grew into the read-model tests) read the market feed and the ticker brief, news feed and deep dive on Postgres, with and without a summary. `test_notify_database.py` checks the alert email quotes the summary. `test_llm_routes.py` adds the regression test for re-summarising news. It also checks that the ticker route lists an answer with no text as that artifact's error and goes on to the next artifact. `test_news_summary_database.py` checks the same for the news loop. 08 (#56) deleted those `test_llm_routes.py` tests and `test_news_summary_database.py` with the inline routes and the news loop. `test_llm_routes.py` now checks that the ticker route queues only artifacts without a complete summary.
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
- The two stores stay for now, as the team decided (the old step 5). 10 moved both readers in #56. Category sentiment reads summaries through `artifact_summary.read`, the watchlist reads the `brief` view through `GET /watchlists/me/summary`, and `GET /artifacts/ticker/{id}` is deleted. Only `/artifacts` and `/artifact-summaries` still return the stores raw, so the team can look again now. If the stores are collapsed, make the summary row the one store.
- Serving the watchlist brief from the `brief` view (the old step 4) was done by 10 in #56, through the watchlist summary endpoint.
- The repair operation still skips announcements with no summary row, as the team decided. `/llm/summarise/ticker/{symbol}` fills those gaps.
- If the model keeps leaving a line empty for some announcements, the ticker route spends an LLM call on each of them on every run. If that shows up in the LLM budget, the team can bring back the old skip rule for announcements in that route.
- `feature/86d4a0a1d-specific_report_sources` is not merged. Its change to `ticker._source_from_values` now belongs in `artifact_card.sources`. The claim-traceability branches (#68 and `feature/86d48cxxz-advanced_traceability`) are not merged either. The chosen one adds `SummaryExtension("claim_evidence", ...)`, required for announcements, to `EXTENSIONS`. It also keeps `claim_evidence` in `AnnouncementSummary.parse`, bumps the prompt version, and adds its field to the card and the clarity view.
- `tools/reclassify_artifacts.py` still reads the whole metadata JSON and writes it back without a lock, so it can overwrite summary keys recorded at the same moment. The local loader's duplicate path, which did the same, went with `parsing/storage.py` (08).
- `record` holds the artifact row lock until the caller commits, so loops commit after each artifact. 08's records adapter, `PostgresAnalysisRecords`, is built on it (#56).
- After deploying, check on staging:
  - Run one analysis. Its summary row has `model_used` and `prompt_version`, and its metadata has all six keys.
  - `uq_artifact_summaries_artifact` exists. `ON CONFLICT` needs it.
  - A dry-run repair gives the same `missing_before` before and after the deploy.
  - The market feed, home page, source library, research summary and deep dive show the empty-summary states.
  - The Brevo alert smoke test passes.

Where the code is: `backend/app/services/artifact_summary.py`, `backend/app/services/artifact_card.py`, `backend/app/crud/artifact.py` (`store_artifact_analysis`), `backend/app/crud/announcement.py`, `backend/app/read_models/ticker_brief.py`, `backend/app/read_models/ticker_records.py`, `backend/app/services/analysis_queue.py` (`request_ticker_summaries`), `backend/lambdas/artifact_analysis.py` (`summarise`, `repair_missing_summaries`), `backend/lambdas/artifact_analysis_records.py`, `backend/scripts/populate_local_content.py`, `backend/app/services/alert_delivery.py` (`_load_alert`, which was notify's `_load_context`), `frontend/src/app/components/announcements/recordPresentation.js`, `frontend/src/app/components/company/companyFormat.js`, `backend/tests/test_artifact_summary.py`, `backend/tests/test_artifact_card.py`, `backend/tests/test_summary_writers.py`, `backend/tests/test_ticker_read_models.py`.

### 09 Category taxonomy ownership

Worth exploring, size S to M. Done in #56. 10 switched the category sentiment view to the buckets, also in #56. Test approach: pure code.

What was wrong
- The classification engine itself is good, but adding a category meant editing 7 places: the taxonomy, `EXTRACTORS`, `CATEGORIES`, the storage `artifact_type` map, `_LEGACY_TO_STABLE`, the `ArtifactType` enum and the sentiment keywords.
- 4 of the 7 extractor classes returned `{}`.
- The documented legacy baseline silently ran rules-v2, so the recorded Macro F1 of 0.4765 could not be reproduced.

What was built

Each `CategoryDefinition` in `parsing/classification/taxonomy.py` owns its facts: its rules, the names it is stored under (`compatibility_category` and `artifact_type`), its display label, its metric extractor if it has one, and its sentiment bucket. `category_definition()` and `artifact_type_for()` read them. `classify_document` did not change, so this stays in line with the classification implementation plan.

Done in #56
1. The real legacy keyword classifier, run from `dabaaf0` (the commit the baseline report names) over the 85 fixtures, reproduces the recorded baseline exactly. Its predictions are frozen in `tests/fixtures/classification/legacy_baseline.json`, and `evaluate_classification --classifier legacy-baseline` replays them. `current` is now the default. `parsing/classifier.py` and `--classifier legacy` are deleted.
2. The four extractor classes that returned `{}` and the `CATEGORIES` list are deleted.
3. Each definition has a label, an `artifact_type` and its sentiment bucket. `parsing/extractors.py` and the local loader's `_CATEGORY_TO_ARTIFACT_TYPE` give way to the definitions. Adding a category now means one definition, plus an `ArtifactType` member if it needs its own stored type. The team decided the buckets are a proposal only, so the category sentiment view still buckets by keyword and no UI numbers change. After the team decided the mapping, 10 switched the view in #56.
4. The mapping below was handed to 10, and the team decided it on 2026-10-13.

| Category | Bucket |
|---|---|
| `quarterly_trading_update`, `guidance_update`, `half_year_results`, `full_year_results`, `annual_report` | revenue |
| `dividend_announcement`, `capital_management` | dividend |
| `corporate_action` | strategy |
| `executive_transcript` | strategy (decided 2026-10-13) |
| `leadership_change`, `governance_meeting` | organisational |
| `regulatory_legal` | risk |
| `security_notification` | none |

Bug found on the way: `Dockerfile.analysis` did not copy `parsing/classification/`, `parsing/extractors.py` or `parsing/classification_metadata.py`, so the analysis handler could not be imported in the deployed image. It had been so on `main` since the rules engine landed (`9816ef6`). Step 1 deletes a file that Dockerfile copied, which is how it came up. The image now copies them, and `test_lambda_images.py` checks that every image ships the backend modules its handler imports and copies no missing path.

Tests
- `test_classification.py` is unchanged, except that its one test of the deleted wrapper is removed.
- `test_category_taxonomy.py` checks every definition is complete, and pins every stored category name and artifact type.
- `test_classification_evaluator.py` checks the frozen baseline still gives the recorded Macro F1, unknown false-positive rate and per-category F1.

Behaviour changes: none from the taxonomy. Stored categories, artifact types and extracted data are unchanged, and the category sentiment view still buckets by keyword, until 10 switched it in #56. The analysis image fix is a deploy change (see Left over).

Left over
- Deploy and check that the analysis Lambda starts. On the current staging stack, search the analysis function's CloudWatch logs for `No module named 'parsing.classification'` to see whether analysis has been failing since `9816ef6`.
- The API image did not ship the taxonomy, so the category sentiment route could not import it. Done by 10 in #56: `Dockerfile.api` copies `parsing/__init__.py`, `parsing/categories` and `parsing/classification`, and the view counts each classified announcement in its category's one bucket, with executive transcripts in strategy and security notifications in none.
- Only the local loader stored a category's own `artifact_type`, and the pipeline stored `asx_announcement_other` for every announcement. Done in #56 by 08: analysis stores the category's type, migration `86d9artifacttypes` sets it on older announcements, and `tools/reclassify_artifacts.py` keeps it in step for announcement rows.

Where the code is: `backend/parsing/classification/taxonomy.py`, `backend/parsing/categories/`, `backend/parsing/analysis.py` (`apply_rules`), `backend/lambdas/artifact_analysis.py` and `backend/tools/reclassify_artifacts.py` (`artifact_type_for`), `backend/tools/evaluate_classification.py`, `backend/tests/fixtures/classification/legacy_baseline.json`, `backend/tests/test_category_taxonomy.py`, `backend/tests/test_lambda_images.py`, `backend/Dockerfile.analysis`.

### 08 Artifact analysis

Strong, size L. Done in #56, on top of 03, 04, 06 and 07. Test approach: services we own behind interfaces with fakes (a fixed sentiment, a scripted LLM, an in-memory raw document store and a list as the alert sender), with the records on real Postgres.

What was wrong
- "Analyse an artifact and record the result" ran as 3 full paths (the worker's documents, the worker's stored text and the local loader), 4 summary-only writers (the repair operation, `news_summary` and the two `/llm/summarise` routes) and 2 sentiment-only writers (`news_sentiment` and `parsing/storage.py`). The summary kind was chosen in 7 places: three times in `parsing/analysis.py`, and once each in `llm.py`, the repair operation, `news_summary` and `parsing/storage.py`. The FinBERT input was built in 5.
- `artifact_type` depended on the path. Discovery created every pipeline announcement as `asx_announcement_other` and analysis never changed it, while the local loader stored the category's own type. Readers use `metadata.category` first, so no label was wrong.
- `lambdas/analysis.py` had 14 import statements inside functions, 11 of them from `app.crud`. They kept `Settings` from being built before SSM loaded `DATABASE_URL`. No test checked that rule.
- The local loader read every document with pypdf alone, so it had no OCR fallback and could not read an HTML, Word or text document. It knew a document by a hash of its extracted text, inserted sentiment with `db.add`, slept 3 seconds after each summary and never set an analysis status. (07 had already moved its summary onto `artifact_summary.record`.)
- Four routes that record a summary generated it inside the API Lambda's 30 seconds: both `/llm/summarise` routes, `POST /news/fetch/{symbol}` (inline summaries for up to 100 stories) and `POST /news/summarise/{symbol}` (up to 200).
- News fetched on demand never got FinBERT sentiment. `/news/fetch` summarised it inline, and the queueing step then refused any story whose summary was complete. `POST /news/sentiment/{symbol}` could not work in AWS, because the API image has no FinBERT.
- `parsing/test_pipeline.py` imported `scrapers.registry.scrape`, which #56 deleted, so it and `parsing/env.py` were dead.

What was built

`lambdas/artifact_analysis.py` analyses one artifact and records the result. It reaches the database, FinBERT, the LLM, S3 and the notification queue only through `AnalysisPorts`: the records, the sentiment scorer (`FinBertScorer`, or `FixedSentiment` in tests), the LLM provider (06), the raw document store (03) and the alert sender. Its entry points are `analyse_stored_document` (an S3 notification), `analyse_downloaded_document` (the local loader), `analyse_stored_text` (news and public discussion), `summarise` (a new summary and nothing else) and `repair_missing_summaries`. Every analysis follows one order: trust checks, reconcile a document, skip a completed artifact, start, read and classify, score, summarise, finish, alert. The module is the one place for the rules that had copies: the summary kind for each kind of artifact, the FinBERT input (`sentiment_input(title, text)`), the document metadata, the artifact type and the alert rule. A `PermanentDocumentError` means a retry cannot help and anything else is retried, so `pipeline_stage.run_stage` (04) still decides between a retry and a final failure. An LLM answer with no text is an outcome, not an error: an analysis records the sentiment without a summary, and `summarise` records nothing and returns `SummaryUnavailable`, as it does when no LLM is switched on.

`lambdas/artifact_analysis_records.py` holds the one records adapter, `PostgresAnalysisRecords`, built on 07's `artifact_summary` and 04's transitions. There is no in-memory fake, because it would have to copy the scrape run counters. `deployed_ports()` builds the Lambda's ports and `local_ports()` the loader's. The analysis Lambda is now a thin handler: it parses each message, names the subject a failure is recorded against and logs the outcome. The API never analyses or summarises an artifact; it queues the work through `app/services/analysis_queue.py`.

Done in Phase 0: the team chose title + raw_text as the one FinBERT input. `sentiment.sentiment_input(title, raw_text)` is used by the worker, the news route and the local loader, and the tests that disagreed were fixed (#62).

Done in #56
1. Stored text. `analyse_stored_text` and the records adapter replace the Lambda's stored-text path and `parsing/analysis.py`'s `analyse_news_text` and `analyse_public_discussion_text`.
2. Stored documents. `analyse_stored_document` keeps the trust checks, the reconcile step and their error codes, and shares the score, summarise and record steps with stored text. The alert rule and `sqs_alert_sender` replace the three notification helpers. `parsing/analysis.py` keeps only extraction and `apply_rules`, and the extraction limits are read where the module extracts. `lambdas/analysis.py` has no function-level imports left.
3. Artifact types. Analysis stores an announcement under its category's type (`artifact_type_for`), stored text keeps its collector's type, and `store_artifact_analysis` takes the type. The team chose to fix older rows too. Migration `86d9artifacttypes` gives the type to `asx_announcement` rows whose category is `DividendAnnouncement`, `SecurityNotification` or `LeadershipChange`, and `tools/reclassify_artifacts.py` sets it when it rewrites an announcement's classification.
4. Summaries. `summarise` writes a new summary from the stored text, category and extracted fields, and leaves sentiment, classification and status alone. An answer with no text records nothing and returns `SummaryUnavailable` with the reason, so the artifact keeps its summary. The IAM-only repair is now `repair_missing_summaries`, a loop over `summarise` with the same selection, result keys, cap of 20 and Bedrock-only guard. It still records a new summary only when it is complete.
5. Message contract. Queueing the admin routes changes the analysis queue's contract, so the rename happened now. `PublicDiscussionAnalysisMessage` is `StoredTextAnalysisMessage`, keeping the wire name `public_discussion_analysis` that queued messages carry, and `SummaryRequestMessage` (`artifact_summary`) is new. `AnalysisRequest` is their discriminated union, read by `analysis_request`, and the worker's `parse_analysis_request` reads either. A summary request has no subject, so a failure records nothing on the artifact.
6. Admin summary routes (team decision). Both `/llm/summarise` routes queue a summary request and answer 202, with no LLM check first. `analysis_queue` owns the selection and the sending (`request_summary`, `request_ticker_summaries`, `send_analysis_request` and `AnalysisQueueUnavailable`), and the routes get the sender through `Depends(analysis_queue.analysis_sender)`. The ticker route takes a `limit` from 1 to 50 (`analysis_queue.MAX_TICKER_SUMMARIES`), because each request is one LLM call. `POST /llm/categorise/recent` still generates inline. The template already gave the API `ANALYSIS_QUEUE_URL` and `sqs:SendMessage` on the analysis queue.
7. Marketaux (team decision). `fetch_and_store_news` stores stories and hands every story, new or stored, to an `analyse` hook, which by default queues it. The `summarise` and `enqueue_analysis` flags are gone. `POST /news/summarise/{symbol}` and `POST /news/sentiment/{symbol}` are deleted with `news_summary.py` and `news_sentiment.py`.
8. Local loader (team decision). `collect_asx` keeps a copy of each document, finds or creates its artifact by `document:{checksum}` with no scrape run, and calls `analyse_downloaded_document`. `collect_news` analyses each story in the same process through the hook. `parsing/pipeline.py`, `parsing/storage.py`, `parsing/test_pipeline.py` and `parsing/env.py` are deleted, and `parsing/print_artifacts.py` stays.

Tests
- `test_artifact_analysis.py` runs the module on Postgres, with `PostgresAnalysisRecords` over a rolled-back session, `FixedSentiment`, a scripted LLM, an in-memory raw document store and a list as the alert sender. It covers:
  - stored text: the news and discussion prompts, untitled posts, no LLM, an answer with no text and a failed LLM call
  - documents: the full flow, reconciling, four kinds of untrusted notification, artifact types, and a downloaded document recorded exactly as the worker records the same bytes
  - alerts: every alertable label, a failed alert, the SQS sender's message and the alert switch in `deployed_ports`
  - summaries: `summarise` for each kind and for an answer with no text, and the repair's dry run, limit, complete-only rule, answer with no text, removed announcement and Bedrock guard
  - one test that all three analysis paths give FinBERT the title and text, and a subprocess test that importing the handler builds no `Settings` (17 replaced it in #56 with one that covers all five worker handlers)
- The analysis tests in `test_pipeline_stages.py` inject ports at `analysis.deployed_ports` and run a real text document, instead of patching `analyse_document` and boto3. New handler scenarios cover stored text, a summary request with and without an LLM, a summary request whose answer has no text (acknowledged, with the old summary kept), and a failed alert.
- `test_llm_routes.py` runs the queued routes with a recording sender, and checks through FastAPI that the ticker route answers 422 for a `limit` of 0 or 51 and 202 for 50. `test_marketaux.py` runs the hook on Postgres, and `test_local_content_loader.py` runs the loader on Postgres with a fake adapter. `test_messages.py` covers the requests, and `test_artifact_type_migration.py` and `test_reclassify_artifacts.py` cover the types. 07's `test_summary_writers.py` now has the worker, the summary request, the repair and the local loader as its writers.
- Deleted as replaced:
  - the tests that patched private functions or checked call order in `test_document_workers.py` (stored-text analysis, notifications and dispatch)
  - the `_publish_notification` tests in `test_alerts.py` and `test_alert_vocabulary.py`
  - the inline summary tests in `test_llm_routes.py`
  - `test_news_summary.py`, `test_news_sentiment.py`, `test_news_summary_database.py`, `test_llm_unavailable.py`, `test_storage_helpers.py` and `test_local_pipeline_classification.py`, with their code. The unavailable-provider test moved to `test_generation.py`.

Behaviour changes
- Pipeline announcements in the three categories with their own type are stored as `dividend_announcement`, `security_notification` or `leadership_change` instead of `asx_announcement_other`, and migration `86d9artifacttypes` gives older rows their type (see Left over for when to run it). No UI label or sentiment bucket changes, because readers use `metadata.category` first and the keyword search treats a snake_case type as one word.
- The summary routes:
  - `POST /llm/summarise/artifact/{id}` answers 202 `{artifact_id, queued}` instead of 200 with the summary.
  - `POST /llm/summarise/ticker/{symbol}` answers 202 with `candidates`, `queued`, `skipped`, `artifact_ids` and `errors` instead of `processed`, `skipped` and `errors`. It also skips artifacts whose analysis is queued or running. Its `limit` must be from 1 to 50 and answers 422 otherwise; it took any value, and a negative one gave a 500.
  - Neither answers 503 for "no LLM" any more. The worker logs `summary_unavailable` with the artifact and the reason, and records nothing, both when no LLM is switched on and when the answer has no text. For an answer with no text the inline artifact route answered 502 and the ticker route listed the artifact under `errors`. Both routes answer 503 when `ANALYSIS_QUEUE_URL` is not set, and the artifact route also when the queue refuses the request.
  - The analysis Lambda writes the summary seconds later, with its 720-second timeout and the flex Bedrock tier.
  - Summary requests are not deduplicated. Calling either route again before the worker has drained the first requests queues the same artifacts again, one LLM call each. The inline ticker route's second call skipped them, because the first had recorded complete summaries.
- Summarising a public discussion post through the artifact route uses the discussion prompt; it used the announcement prompt. An untitled news story is summarised as "Untitled news article", the worker's placeholder, not "Untitled news story".
- `POST /news/fetch/{symbol}` stores stories and queues every one not yet analysed, so news fetched on demand gets FinBERT sentiment and a summary from the worker. It no longer summarises inline, and its response drops `summarised`. Stories summarised inline before are queued the next time they are fetched, which costs one more LLM call each.
- `POST /news/summarise/{symbol}` and `POST /news/sentiment/{symbol}` answer 404.
- A message with an unknown `message_type` fails as `invalid_message` instead of `invalid_s3_event`. Both are permanent.
- Three failure texts in the repair's result change. An incomplete answer reads "RuntimeError: The generated summary omitted structured summary fields" (it began "Bedrock response"), an answer with no text reads "RuntimeError: The answer from <model> has no text", and an announcement removed mid-repair reads "PermanentDocumentError: Artifact does not exist" (it read "RuntimeError: Completed artifact is no longer available").
- A document's title is stripped before classification, FinBERT and the summary, and a blank one becomes "Untitled ASX announcement", as stored text's title already was. Only a title with leading or trailing whitespace gets a different input.
- The local loader now analyses documents as the worker does:
  - every format the worker reads (PDF, HTML, Word and text), with its page limits and OCR fallback, where it read everything with pypdf
  - `page_count` and `document_format` in the metadata
  - `analysis_status` completed, and the sentiment stored with the text and summary in one transaction instead of inserted on its own
  - FinBERT sentiment for local news too, which it only summarised inline
  - no 3-second sleep per summary
  It knows a document by `document:{checksum}` instead of a hash of its extracted text, so a local database gets one new row for each document loaded before, and the oversized-title repair for old duplicates is gone. An already analysed document is summarised again only while its summary is incomplete. The six-field summary with its prompt version, the classification metadata and the category's type are stored as before.
- Locally without the LocalStack overlay, the summary routes answer 503 and `/news/fetch` stores stories without queueing them. The overlay now sets `ANALYSIS_QUEUE_URL` for the API.
- `notification_publish_failed` now carries `duration_ms`, like the other stage events.
- Unchanged: the prompts and prompt versions, the other log events and their fields, `NotificationMessage`, run counters and status transitions. FinBERT still scores the title and text, apart from the title change above.

Left over
- Check on staging:
  - The analysis image imports `lambdas.artifact_analysis` on a cold start.
  - `POST /llm/summarise/artifact/{id}` answers 202, and the worker logs `completed` with the Bedrock model and the current prompt version.
  - `POST /llm/summarise/ticker/{symbol}` with `limit=50` does not set off flex-tier throttling or the analysis dead-letter alarm.
  - `POST /news/fetch/{symbol}` queues stories that then gain sentiment rows.
  - The analysis log events keep their fields, and a notification still reaches its queue.
- Run the `86d9artifacttypes` backfill a second time. No workflow runs migrations: the operator applies them by hand before the release (`infra/README.md` §4), and the old analysis image keeps storing `asx_announcement_other` until the new one is live. Once it is, run the backfill again from `backend/` with the migration database URL: `python -m alembic downgrade 86d9engagement`, then `python -m alembic upgrade head`. That is safe while `86d9artifacttypes` is still the head, because its downgrade does nothing and its upgrade can run twice; otherwise run its three UPDATEs by hand. Do the same after any rollback of the analysis image. Compare `SELECT artifact_type, count(*) FROM artifacts WHERE source_type = 'asx_announcement' GROUP BY 1` before the first run and after the second.
- Deploy the API and analysis images together. An older analysis image drops a summary request as `invalid_s3_event` (a `permanent_failure` with no `artifact_id`), because it reads any message that is not stored-text analysis as an S3 notification; send it again.
- A failed summary request records nothing on the artifact. Its only traces are the log events and the message in the analysis dead-letter queue. The failure log lines carry no `artifact_id`, because a summary request has no subject; `summary_unavailable` and `completed` do.
- The ticker route queues at most 50 summary requests, but the analysis event source has no `MaximumConcurrency`, so they can start 50 flex-tier Bedrock calls at once, and calling the routes again before the worker has drained them queues the same artifacts again. A throttled request is retried only after the 72-minute visibility timeout, and reaches the dead-letter queue after 5 receives. `MaximumConcurrency` on the analysis event source would bound this, but it would also slow pipeline analysis.
- `POST /llm/categorise/recent` and the investor route `GET /reddit/ticker-sentiment/{t}` still generate inside the API's 30 seconds.
- The worker's six environment reads (`MAX_PDF_PAGES`, `MAX_OCR_PAGES`, `MAX_OCR_PIXELS_PER_PAGE`, `RAW_DOCUMENT_BUCKET`, `NOTIFICATIONS_ENABLED` and `NOTIFICATION_QUEUE_URL`) were left for 17. Done by 17 in #56: they come from `settings`, and generation and the sentiment service are imported at the top. The records and the artifact summary module stay imported on use, because the records module imports `artifact_analysis` and importing any model creates the engine.
- The IAM Sid `EnqueuePublicDiscussionAnalysis` now also covers summary requests. Renaming it is optional.
- Local databases keep the documents the old loader stored under text hashes, next to the new `document:` rows. Delete them by hand if they get in the way.

Where the code is: `backend/lambdas/artifact_analysis.py`, `backend/lambdas/artifact_analysis_records.py`, `backend/lambdas/analysis.py`, `backend/parsing/analysis.py` (extraction and `apply_rules`), `backend/app/messages.py` (`StoredTextAnalysisMessage`, `SummaryRequestMessage`, `AnalysisRequest`), `backend/app/services/analysis_queue.py`, `backend/app/api/routes/llm.py`, `backend/app/api/routes/news.py`, `backend/app/services/marketaux.py` (`fetch_and_store_news`), `backend/app/crud/artifact.py` (`store_artifact_analysis`), `backend/scripts/populate_local_content.py`, `backend/tools/reclassify_artifacts.py`, `backend/alembic/versions/86d9artifacttypes_store_announcement_artifact_types.py`, `backend/tests/test_artifact_analysis.py`, `backend/tests/test_pipeline_stages.py`, `backend/tests/test_llm_routes.py`, `backend/tests/test_marketaux.py`, `backend/tests/test_local_content_loader.py`, `backend/tests/test_artifact_type_migration.py`.

## Phase 4: read side

### 10 Ticker read-models

Strong, size M. Done in #56. Needs 01, 07 and 09, all done in #56. Unblocks the decision on collapsing 07's two summary stores. Test approach: real Postgres, with a fixed quote source in place of Yahoo.

What was wrong
- `ticker.py` was 342 lines. 01 had removed its catalogue data and 07 its card code, but it still mixed the Yahoo quote client and its module-level cache, eight formatters, the brief builder, the CRUD routes and three page reads. The brief's tests patched private functions (`_live_quote`, `_ticker_artifacts`, `_latest_sentiment_for_ticker`).
- `category_sentiment.py` (434 lines) held the whole read inside the route file: the keyword table, the query, the bucketing and the weighting. Its lookup only upper-cased the symbol, so `/sentiment/BHP.AX` answered 404 where `/brief` did not. Its POST compatibility route either repeated the GET or answered 503, and the README still described a Bedrock and FinBERT pipeline it no longer ran.
- Buckets were guessed from keywords in the title and summary lines, ignoring the rules-v2 classification. A classified announcement counted in every bucket its text matched, or in the strategy catch-all. 09's buckets went unread, because the API image did not ship `parsing/`.
- The latest signal was the newest sentiment row of any artifact stored against the ticker (`_latest_sentiment_for_ticker`). The headline went to whichever artifact was analysed for the first time last: an older filing analysed after a newer one (for example in a batch analysed out of order, or on a retry), or a news story. Analysing a filing again never moved it, because analysis updates an artifact's one sentiment row in place and keeps the row's time. The UI calls it the latest filing signal, and the story beside it told the newest published record.
- The watchlist page built its own read-model in the browser. It fetched `/auth/me`, `/watchlists/me` (taking the first of an unordered list) and `/watchlist-tickers/{id}`, then `/tickers/{id}` and `/artifacts/ticker/{id}` for each company. The last sent every artifact with its raw text, with no limit. To avoid more calls the cards showed no signal, and the page's private `fetchJson` silently ignored a failed add or remove.
- Nothing read the brief's deprecated `public_sentiment_pct`, and the frontend filtered out the key numbers that repeated the price and day change. Once #42 deleted `DeepDiveTimeline.jsx`, nothing showed the deep-dive event's `month`, `metrics` or `tone`. `DeepDiveNotebook.jsx` fell back to `month` only when `date` was missing, and `date` is always set. It hid every metric that starts "Source:", which is the only kind sent. Nothing read the constant `tone: "green"`. The search page kept a dead `{tickers: [...]}` branch.
- The check that the API never runs FinBERT searched the text of `Dockerfile.api` and the route file.

What was built

`app/read_models/` holds the read-models. Each answers one page's question from stored data (the brief also uses a live quote) and writes nothing. Its route only translates HTTP: it reads the parameters, calls one read function, turns `TickerNotFound` into a 404 and declares the response schema. `ticker_records` finds the ticker (`find_ticker` accepts any case and a `.AX` suffix) and reads its records, the artifacts stored against it, newest published first. `recent_artifacts` loads each record with its summary and platform, in two more statements however many records there are. `latest_artifacts` gives every ticker's newest record in one query plus the load of its summaries. `read_news_feed` and `read_deep_dive` build the feed and the research history from 07's artifact card (`artifact_card`, `tag` and `sources`) and summary views. `ticker_brief.read_ticker_brief(db, symbol, quotes=...)` builds the brief from one quote and five statements: the ticker lookup, the artifact query with the loads of its summaries and platforms, and the signal query. `ticker_sentiment` is the one definition of a ticker's sentiment. `latest_signals` reads the latest filing signal of any number of tickers in one query, and `read_category_sentiment` returns the existing `CategorySentimentResponse`. Its bucket rule, `buckets_for`, asks the taxonomy first (`taxonomy_buckets_for`): a discussion post counts in public discussion, and an announcement stored under a taxonomy category counts in that category's one bucket, or in none. Keywords (`keyword_buckets_for`) place the rest. `counted_label` decides which stored labels count. The API image ships `parsing/__init__.py`, `parsing/categories` and `parsing/classification`, which use only the standard library, so each stored category's bucket is looked up at request time and a mapping change needs no backfill. `watchlist_summary.read_watchlist_summary` answers the watchlist page in five statements, whether one company is watched or many: the watchlist, its companies, their latest signals, and their newest records with those records' summaries.

Quotes come through `app/services/quotes.py`. A `Quote` is a price and a previous close. `YahooQuotes` is the old client, with its transport and clock injectable and a cache of its own. `FixedQuotes` answers from a table in tests. `live_quotes` is the FastAPI dependency, and it keeps one `YahooQuotes` per process.

Done in Phase 0
- The `confidence or 1.0` weighting bug is fixed, and keywords match whole words only (#62).
- The dead `category_sentiment.py` helpers and the `/overview` and `/brief-aside` routes are deleted (#64).

Done in #56
1. The quote source. The brief gets it from `Depends(live_quotes)`, and a direct call of the route passes `quotes=`. The cache windows are unchanged: five minutes for a quote, one minute for a failure.
2. The ticker sentiment read-model (the old step 2). Category sentiment and the latest signal moved out of the route files. `buckets_for` and `aggregate_bucket` are public and tested without a database. The discussion source types come from `PUBLIC_DISCUSSION_SOURCE_TYPES` and the labels from `SENTIMENT_LABELS`. Summaries are read through `artifact_summary.read` instead of the top-level metadata keys.
3. The ticker brief read-model (the old step 1) and its `TickerBrief` schema. The brief drops `public_sentiment_pct` and the repeated "Current price" and "Day change" key numbers. `artifact_card.tag` is now the one tag of an artifact, shared by the card, the deep dive and the brief's "Latest type" and themes.
4. The news feed and deep dive read through `ticker_records`, with `NewsFeedRecord` and `DeepDiveEvent` schemas. 07 had already batched the deep dive's summary query with `WITH_SUMMARY` (the old step 5).
5. Deep-dive events drop `month`, `metrics` and `tone` (the old step 6). `DeepDiveNotebook.jsx` drops its fallback to `month` and its filter of `metrics`, neither of which ever showed anything. No frontend change was needed first.
6. `GET /watchlists/me/summary`, and the watchlist page moved onto it (the old step 4, with 07's old step 4). The page asks for the investor, then the summary. `lib/api.js` gains the investor, summary and watchlist edit calls, and its `fetchJson` reports each message of a validation error. `lib/watchlists.js` gains `watchlistCard`. Each card's brief is 07's `brief` view of the company's newest record.
7. The team decided to delete the two routes nothing calls once the page moved, in the same change: `GET /artifacts/ticker/{ticker_id}` with `crud.artifact.get_artifacts_by_ticker`, and `POST /sentiment/{ticker}` with `CategorySentimentRequest` and `RedditSummary`. The README lists `GET /sentiment/{ticker}` in place of the POST row.
8. The search page's dead branch is gone. The market feed's company links already came from `tickers.json` (`fd5ad9c`).
9. The team decided to look each bucket up at request time. `category_for_compatibility` finds a definition by the metadata category name it is stored under, and `artifact_type_for` reads the same table. The read-only `tools/compare_sentiment_buckets.py` prints the keyword rule and the taxonomy rule side by side for each catalogue ticker, with the keyword fallback's share and the artifacts that move. Like the view, it leaves out rows whose label is not a sentiment label, so each count it prints is the research summary's source count.
10. The team decided the mapping on 2026-10-13, and the view now uses it: 09's table, with one bucket per classified announcement, executive transcripts in strategy and security notifications in no bucket. News and the announcements the taxonomy cannot place (no category, `UNKNOWN`, `news_article`, older rows whose category names no definition) keep keyword matching, and discussion posts stay in public discussion. An announcement the rules marked `needs_review` has a primary category but is stored as `UNKNOWN`, so it keeps keyword matching too.
11. The team decided the latest filing signal on 2026-10-13: the sentiment of the ticker's most recently published ASX announcement with a valid label, ordered by `coalesce(published_at, created_at)`, then by the sentiment's time. It is one query for any number of tickers, and the brief and the watchlist cards both use it. Its analysis time is when that filing was first analysed, because analysing it again keeps its sentiment row's time.
12. The team decided not to wait for the citation branches. The brief's sources and clarity, and the feed's cards, are unchanged.

Tests
- `test_quotes.py` (pure) gives `YahooQuotes` an httpx mock transport and a fake clock. It checks the request, the price, the previous close and its fallback, six answers that give no quote, both cache windows, `FixedQuotes` and the day change.
- `test_ticker_read_models.py` grew from 07's `test_ticker_routes.py`. It reads every ticker read-model on Postgres. Six of its tests make torch and transformers impossible to import (`without_model_runtime`): the empty brief, the brief's latest signal, three category-sentiment reads and `latest_signals`. Neither library is installed outside the Docker image job, so elsewhere the fixture blocks nothing (see Left over). It covers:
  - the brief: an empty brief, the quote and its one lookup, the latest signal, the story and clarity, the key numbers and themes, the `.AX` suffix, and its schema and 404 through TestClient;
  - the records: the card fields, the summary text as the detail, the ten newest records newest first, the routes' schemas and 404, and the event's five keys;
  - a statement count that reads one record and ten, each with its own platform, and expects the same number of queries (without the platform eager load the feed goes from 4 to 13);
  - category sentiment: buckets, no analysis, a post linked only by a mention, the window, the `.AX` suffix, an unknown ticker, and a dividend announcement counting only in dividend, a security notification in none and news by keyword;
  - the latest filing signal: an older filing analysed for the first time after a newer one, news, a discussion post and an invalid label never become it, and an undated filing counts by its collection date;
  - the comparison tool, including that a row the view skips, such as one labelled "mixed", counts nowhere and is not listed as moved.
  Pure cases cover each category's one bucket, the keyword fallback and the confidence weighting.
- `test_watchlist_summary.py` runs on Postgres. It covers no watchlist, a company's signal and brief beside a bare one, an undated record, another investor's watchlist, the oldest watchlist, the added order, one company and three costing the same number of statements, the card and the brief showing the same signal, and the route's 401 and schema through TestClient.
- `test_lambda_images.py` replaces the source-text check. The API image installs neither torch nor transformers, and the analysis image installs both, so the rule can fail. Every API image handler imports in a subprocess with both blocked. The parsing code the API image ships imports only the standard library, which CI's full install would otherwise hide. `test_category_taxonomy.py` finds each definition by its stored name.
- Vitest covers the card's status, tone, brief and dates, the summary request's credentials, the validation message and a signed-out investor.
- These replace the MagicMock brief, category sentiment and POST tests in `test_apis.py` (the old lines 34-90, 214-221 and 255-353), the Mastodon mention test and the two brief tests in `test_database.py`, `test_category_sentiment_buckets.py`, which imported private functions, and `test_deployment_contracts.py::test_api_image_does_not_own_finbert_inference`. No test patches a private ticker function now.

Behaviour changes
- The category sentiment numbers change. A classified announcement counts in one bucket instead of every bucket its prose matched, or the strategy catch-all. Security notifications leave the topics. Strategy shrinks most, and a topic only the catch-all filled can become unavailable, which turns the status from available to partial. Each topic's label, source count, summary, evidence, confidence and dates change with it. Public discussion does not change, and news is placed as before.
- An Appendix 2A notice ("Application for quotation of securities") is not classified as a security notification. Its "Total number of +securities on issue" line matches the security notification body rule `securities_on_issue`, which scores 0.2, below the 0.25 evidence threshold, so the rules call it unknown. If it also says "issue of ordinary securities", it scores 0.4 and needs review, with security notification as its primary category. Either way it is stored as `UNKNOWN`, so it keeps keyword matching and lands in strategy unless its summary names a keyword. It does not yet count in no bucket as the team decided (see Left over).
- The latest signal on the brief and the watchlist cards is now the latest published filing's. Before, it was the sentiment of whichever artifact stored against the ticker was analysed for the first time last. News and public discussion never set it.
- Watchlist cards show the latest signal again, for example "Positive Sentiment" in green, instead of "<sector> Monitoring". The page makes two API calls instead of three plus two per company, and downloads no raw text. Companies come in the order they were added, and the investor's oldest watchlist is the one shown. A failed add or remove now shows an error or reloads the list.
- `/sentiment/{symbol}` accepts a `.AX` suffix, where it answered 404, and reports the stored symbol.
- `GET /artifacts/ticker/{ticker_id}` answers 404 and `POST /sentiment/{ticker}` 405. A watchlist page from before this change shows no brief until the new frontend is published, so publish the frontend after the backend deploy, as the release order already does.
- The brief no longer sends `public_sentiment_pct` or the "Current price" and "Day change" key numbers, and deep-dive events no longer send `month`, `metrics` or `tone`. The frontend dropped its filters and fallbacks for them.
- Rolling the backend back past this change needs the frontend rolled back too, as `infra/README.md`'s rollback procedure already does. Against the old backend the new watchlist page fails outright: the old router has no `/watchlists/me/summary`, so it answers 404 and every investor sees "Your watchlist is unavailable right now". "Filing details" also shows the price and day change again.
- The brief, news feed, deep dive and watchlist responses are checked against response schemas. Their JSON is otherwise unchanged.
- The category summary paragraph and the keyword search read summaries through `artifact_summary.read`. For older rows that kept only the joined text, they now see the lines recovered from it.
- The API image also ships `parsing/__init__.py`, `parsing/categories` and `parsing/classification`.
- The quote cache belongs to the `YahooQuotes` instance. There is still one per process, with the same windows.

Left over
- Not checked locally, because the local database has no artifacts and no Lambda runs here:
  - Run `python -m tools.compare_sentiment_buckets` against staging with read-only credentials, and share each ticker's before and after with the team.
  - After deploying, check that ApiFunction and the Scheduler, Notification and PublicDiscussionScheduler functions, which share the image, start with no `ImportError`, that `GET /api/sentiment/BHP` answers, and that `GET /api/tickers/symbol/BHP/brief` still shows a live price from Lambda's network.
  - After the backend deploy and the frontend publish, check that the staging watchlist page itself makes two API calls, `/auth/me` and `/watchlists/me/summary`, makes no `/tickers/{id}` or `/artifacts/ticker/{id}` calls, and shows signals. A fresh load shows a third call, AppFrame's own `/auth/me`.
  - The "Backend Docker image build and test suite" job is the only run with torch installed, and with Python 3.11, the API image's version. It is the only place the blocked-import tests hide a real library.
- Appendix 2A notices count by keyword. To leave them out of the topics as decided, `security_notification` needs the Appendix 2A form and its title phrase, with fixtures, an evaluator run and a classifier version bump, so that `tools.reclassify_artifacts` re-runs stored announcements. That is a rules change under the classification plan.
- The brief's story, sources, clarity and `last_updated`, and the aside's "Latest filing" and "Latest type" key numbers, describe the ticker's newest record of any source type, which can be a Marketaux story. The latest filing signal beside them is always the newest ASX announcement's. So one brief can show a news story's date and type as its "Latest filing" next to a filing's signal. This was so before 10, and decision 3 makes it easier to see. Taking only the key numbers from the newest filing among the brief's 20 records would make them disagree with the story instead, and those records may hold no filing. The team can decide whether the brief tells the latest filing, which costs one more query, or whether the page calls these the latest record. Until then the read-model's docstring and the contract doc say what the key numbers describe.
- Both readers that needed 07's top-level summary keys have moved: category sentiment reads through `artifact_summary.read`, and the watchlist reads the `brief` view through its summary. Only `/artifacts` and `/artifact-summaries` still return the stores raw, so the team can decide now whether to collapse them.
- `components/sources/CitationLinks.jsx` and `components/ui/MetricCard.jsx` are still imported nowhere. Whether to delete them waits on how the chosen citation branch shows sources.
- `AppFrame.jsx` and the sign-in and sign-up pages still read `/auth/me` and validation errors their own way. `lib/api.js` now has `fetchCurrentInvestor` and the error rule they could use.
- `aggregate_bucket` still reports "Multiple stored models" for a topic whose rows name no model, as it did before.

Where the code is: `backend/app/read_models/` (`ticker_records.py`, `ticker_brief.py`, `ticker_sentiment.py`, `watchlist_summary.py`), `backend/app/services/quotes.py`, `backend/app/services/artifact_card.py` (`tag`), `backend/app/schemas/ticker_brief.py`, `backend/app/schemas/ticker_records.py`, `backend/app/schemas/watchlist_summary.py`, `backend/app/schemas/category_sentiment.py`, `backend/app/api/routes/ticker.py`, `backend/app/api/routes/category_sentiment.py`, `backend/app/api/routes/watchlist.py`, `backend/parsing/classification/taxonomy.py`, `backend/Dockerfile.api`, `backend/tools/compare_sentiment_buckets.py`, `frontend/src/app/lib/api.js`, `frontend/src/app/lib/watchlists.js`, `frontend/src/app/watchlist/page.jsx`, `frontend/src/app/components/company/ResearchSummary.jsx`, `frontend/src/app/components/company/DeepDiveNotebook.jsx`, `docs/ticker-rebuild-contract.md`, `backend/tests/test_quotes.py`, `backend/tests/test_ticker_read_models.py`, `backend/tests/test_watchlist_summary.py`, `backend/tests/test_lambda_images.py`.

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
2. Notify sends through `configured_sender(paced=True)` and maps the outcome in `_send_rendered`. `_send_alert`, its lock and its pacing globals are gone. 12 (#56) then moved the mapping into alert delivery's `_Delivery._send`, and notify now asks for the paced sender once per invocation.
3. `PUT /notifications/preferences` and `POST /notifications/preferences/resend-verification` get the sender from `Depends(current_sender)`. `_send_verification_email` maps the outcome through one table, `_UNSENT_VERIFICATION`, and logs only the outcome type and code, never the address. The callers' undo, which marks verification failed, is unchanged. 14 (#56) then moved the send into the alert subscription module, and the route turns its refusals into answers through `_refusals_answered`.
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
- Live alert sends stay at least one second apart within one Lambda container (see [Decisions still needed](#decisions-still-needed)). A dry run is never paced. Containers do not share the pacer, and the template no longer sets reserved concurrency (`test_deployment_contracts.py:145`), so this is not a global rate limit.

Tests
- `test_email_sender.py` (pure) covers the recording sender and `check_message`, including links `urlsplit` rejects and HTTPS only when required. It also covers stable dry-run ids, `SendPacer`, and `configured_sender` following the dry-run switch, with `paced=True` sharing `ALERT_PACER`.
- `test_brevo_alerts.py` is now the Brevo adapter test. It gives the adapter an `httpx.MockTransport` client, so nothing is patched. It covers the payload and the `List-Unsubscribe` header, each refusal class without Brevo's message text, a transport error, and a success without a message id. It also covers the settings and email checks made before any request, including empty, schemeless, angle-bracketed, multi-line and unparseable base URLs, and pacing.
- `test_alert_delivery.py` drives `notify.handler` on Postgres, with savepoint sessions and the recording fake. It checks each outcome against the ledger row, the subscription mirror and `batchItemFailures`. It also covers a retried record sending exactly one alert, a dry run, a malformed Brevo base URL with the real sender, and notify asking for the paced sender.
- `test_alert_subscriptions.py` calls the routes through `TestClient(main.app)` on Postgres. Enabling alerts emails a link that verifies the address. An unsent email answers 422, 502 or 500 by outcome, with verification failed. A refused resend answers 422, and a malformed Brevo base URL with the real sender answers 500.
- `test_notify_database.py` uses the recording fake instead of patching `brevo_alerts.send_email`. `test_notify.py::test_runtime_configuration_load_precedes_configured_imports` now anchors on the `email_sender` import (17 deleted it in #56).
- Deleted:
  - the eight `send_email` tests in `test_brevo_alerts.py` and their transport fixtures;
  - in `test_notify.py`, `test_brevo_success_marks_the_delivery_sent`, `test_terminal_brevo_rejection_is_recorded_and_acknowledged`, `test_retryable_brevo_throttle_is_recorded_before_batch_retry` and `test_live_send_limiter_spaces_fanout_calls`, with the `_brevo_error` helper;
  - `test_alerts.py::test_terminal_brevo_error_updates_ledger_and_subscription`, with `_message_rejected`;
  - `test_notification_preferences.py::test_verification_email_contains_current_signed_app_link`.

Left over
- Real one-click unsubscribe stays optional and out of scope. Phase 0 stopped sending `List-Unsubscribe-Post` (#62). Real support would need an API-backed POST endpoint behind the `/api/*` CloudFront behaviour, added to the public allowlist in `test_access_policy.py`.
- A global send limit needs Brevo's real send-rate limit for the account first.
- Not checked locally: one real verification email and one real alert through Brevo on staging. That needs the Brevo key in SSM, a verified `ALERT_SENDER_EMAIL`, `NotificationsEnabled=true` and a deploy. Check that both emails link to the custom domain and that verification and unsubscribe work from a real inbox.

Where the code is: `backend/app/services/email_sender.py`, `backend/app/services/brevo_alerts.py:94-171` (`BrevoEmailSender`), `backend/app/services/alert_delivery.py:475-487` (`_Delivery._send`, which was notify's `_send_rendered`), `backend/lambdas/notify.py:112` (the paced sender), `backend/app/api/routes/notification_preferences.py:90-103` (`_UNSENT_VERIFICATION`) and `backend/app/services/alert_subscriptions.py:544-579` (`_send_verification` and `_verification_outcome`, which replaced the route's `_send_verification_email` in 14).

### 12 Alert delivery

Strong, size M. Done in #56. Needs 13. 14 builds on it. Test approach: real Postgres with a fake email sender (13's `RecordingEmailSender`).

What was wrong
- `_ensure_rollup` and `_process_watcher` in `notify.py` repeated the same steps: claim, check the recipient, the budget and the preferences, render, send and record the result. Only the cap check, the rollup's count and template, and a `confirmation_checked` flag differed.
- The cap and budget checks are only correct because the claim is committed first. Only a test name and the docstrings of `count_budget_commitments_last_24h` and `_returning_delivery` said so.
- The delivery status names were written out again in the model's CHECK constraint, the crud module, notify and the settings page. The verification statuses and the default threshold of 0.75 were repeated too.
- The ledger had five `mark_*` pass-throughs over one guarded update. The worker wrote the subscription's copy of the newest outcome itself, the "D17" fields `last_delivery_status`, `last_delivery_error_code` and `last_delivery_at`. `get_delivery` and `count_sent_last_24h` had no production caller.
- `test_notify.py` had 64 `monkeypatch.setattr` calls (70 with `setenv` and `delenv`) across 14 private functions, and `test_alerts.py` repeated several of its tests. On Postgres, only the happy path, dedupe and 13's send outcomes were tested end to end.

What was built

`app/services/alert_delivery.py` is the alert delivery module. Its one entry point, `deliver_alerts(message, *, sender, open_session)`, loads the analysed artifact, then delivers to each investor watching its ticker on their own. One decision, `_Delivery.attempt(kind)`, claims, checks, sends and records either a direct alert or the run's rollup. A direct alert past the per-run cap is suppressed and becomes the rollup. A comment at the claim states the claim-first rule. The module raises `AlertNotReady` (retry) or `AlertMismatch` (drop) and returns one `WatcherResult` per investor. An investor whose attempt raises gets a `retry_code`, and the others still get their alerts.

Behind it, `app/crud/alert_delivery.py` is the delivery ledger. `claim(kind)` commits and returns a `Lease`, or `Held` with the status of the row that kept it. `record(lease, outcome)` writes the guarded outcome and the subscription's copy of it in one savepoint and commits, or raises `LeaseLost` or `SubscriptionGone` and writes nothing. `over_run_cap`, `over_daily_budget` and `capped_count` answer the limits. Every claim commits before its send, so only one claim holder sends a row's email at a time. Delivery is still at least once, though: if a stale claim is taken over, or the provider's answer is lost after it took the email, the email can go out again.

`app/alert_vocabulary.py` names `DeliveryKind`, `DeliveryStatus`, `VerificationStatus`, `DELIVERY_PROBLEM_STATUSES` and `DEFAULT_ALERT_MIN_CONFIDENCE`. `lambdas/notify.py` is the SQS adapter: it parses each record, asks for the paced sender once per invocation, logs budget suppressions from the results and keeps the `batchItemFailures` contract.

Done in Phase 0: `app/alert_vocabulary.py` holds the alert labels and the default rule's labels, and neutral alerts work end to end. `test_notify_database.py` now runs for negative and neutral (#60). The default minimum confidence of 0.75 stayed in the schema and the rule model until #56. 17 (#56) takes the setting's default from the constant.

Done in #56
1. Handler scenarios on Postgres, written against the old code. `test_alert_delivery.py` drives `notify.handler` with savepoint sessions and the recording sender. `test_notify_database.py` checks with real commits that the claim is committed before the email goes out.
2. The private-seam tests in `test_notify.py` and their copies in `test_alerts.py` are deleted. This had to come before the move, because they patch the functions it removes.
3. The alert delivery module, with one decision for both kinds. `_load_context` moved whole as `_load_alert`, including 07's `alert_text` read. notify keeps only the SQS contract.
4. The delivery and verification statuses and the default threshold are named once in the vocabulary. Both CHECK constraints are built from the enums and render exactly as migration `86d4k9m2p` created them, so no migration is needed. The response schema, the crud verification statuses and the schema and rule model defaults use the vocabulary. `Settings.ALERT_DEFAULT_MIN_CONFIDENCE` stays, and 17 declares it with the constant as its default.
5. The delivery ledger, with one claim for both kinds and one `record` for every outcome. The five `mark_*` functions, `claim_rollup`, `get_for_artifact`, `get_rollup`, `get_delivery`, the four counters and `alert_subscription.record_delivery_outcome` are deleted.
6. The settings page names its `DELIVERY_PROBLEM_STATUSES`, and tests check it and the `VERIFICATION_COPY` keys against the vocabulary. The page's copy does not change.
7. Review fixes:
   - The deleted notify tests checked three things that no scenario covered, so removing the code behind them left every test green. Scenarios now cover all three:
     - One investor's attempt fails after its claim, because the sender raises, another worker takes the claim over, or the subscription is deleted. The other investors still get the alert, and the record is retried with that attempt's code.
     - A record finds its alert already claimed by another worker or rejected, or its rollup already claimed. The record is acknowledged and nothing is sent.
     - A rollup retried on redelivery checks the address, the daily budget and the preferences again.
   - Each of these scenarios fails when the code it guards is removed: either `except` clause in `_deliver_to`, `claimed` or `rejected` in the settled statuses, or the rollup's address, budget or preferences check.
   - The ledger docstring and the crud README no longer say an alert goes out at most once (see What was built).
   - The `WatcherResult` docstring now says `kind` is also None when an attempt raised after its claim or its send. The `AlertNotReady` docstring now also covers a confidence or rule threshold that cannot be read.

Tests
- `test_alert_delivery.py` runs the handler on Postgres through these cases:
  - dedupe, and a delivery another worker already holds or that is already rejected;
  - fan-out across overlapping watchlists, and one investor's temporary refusal or failed attempt not blocking the others;
  - the rule filters and the 0.75 boundary, and unverified addresses;
  - the per-run cap and its one rollup, and a rollup retried after a refusal, with its address, budget and preferences checks on that retry;
  - both sides of the daily budget, and preferences saved after the claim;
  - a record not visible yet, a record that disagrees with its artifact, the switched-off handler and a mixed batch;
  - the alert links and the logs.
- Together with the ledger tests below, these replace 20 tests in `test_notify.py` and six in `test_alerts.py`. The step 1 scenarios passed unchanged through steps 3 to 5.
- `test_alert_crud.py` tests the ledger through its interface on Postgres. It covers held and stale claims, failed rows claimed again, a run mismatch refused, an outdated lease recording nothing, and sent, rejected and suppressed rows that stay final. It also covers rollup sends stored as `rollup_sent`, the counters, every committed claim counting against the cap, and the subscription's copy written with the row or not at all, never replaced by an older outcome. It replaces the SQL-text tests and the detached-row test.
- `test_status_constraints.py` checks both alert status columns accept exactly their enum. `test_alert_vocabulary.py` checks the page's two lists and the default threshold.

Behaviour changes
- The handler writes the notify `suppressed` log line from the results, with `kind` and both ids instead of `rollup`. The template has no alarm or metric filter that reads it.
- notify no longer logs `investor_skipped`. Nothing after the artifact load could raise the error it logged.
- notify asks for the email sender once per invocation instead of once per send. It is the same paced sender.
- The OpenAPI schema names `VerificationStatus` as a component. The JSON does not change.
- Ledger statuses, error codes, retry decisions, the per-run cap, the daily budget, rollup recovery and the subscription's copy behave as before. There are two differences, and neither can happen with today's senders: their codes are never empty, and are either fixed names or Brevo codes cleaned down to letters, digits, `_`, `.` and `-`.
  - A sender answering with an empty error code would now store no code. The ledger used to store `rejected` or `retryable_failure`.
  - An error code containing a line break is now stored. The old `record_delivery_outcome` refused it with a `ValueError`, which left the row claimed and retried the record.

Left over
- The settings page still shows raw status and code text, such as "The email service reported preferences_changed" and "Last delivery: suppressed_cap". Plain-language copy is a separate UI change.
- `alert_delivery._links` built the news and unsubscribe links. Done by 14 in #56: alert delivery asks `alert_subscriptions.alert_links` for an alert's links, and `_links` is gone.
- `Settings.ALERT_DEFAULT_MIN_CONFIDENCE` repeated `DEFAULT_ALERT_MIN_CONFIDENCE`. 17 kept it in #56, because `alert_subscriptions._preferences` reads it for an investor with no rule, and takes its default from the constant (see 14's Left over).
- Live sends are still spaced one second apart per Lambda container (13). Brevo's real account limit is unknown.
- Check that no manually created dashboard or alarm parses the old `rollup` field of the `suppressed` log line, or the `investor_skipped` event notify no longer logs.
- `last_delivery_status` has no CHECK constraint. On staging, `SELECT last_delivery_status, count(*) FROM alert_subscriptions GROUP BY 1` should show only `DeliveryStatus` values.
- `backend/app/models/README.md` still says the schema has ten tables and leaves out the three alert tables.

Where the code is: `backend/app/services/alert_delivery.py`, `backend/app/crud/alert_delivery.py`, `backend/app/alert_vocabulary.py`, `backend/lambdas/notify.py`, `backend/app/models/alert_delivery.py`, `backend/app/models/alert_subscription.py`, `backend/app/models/alert_rule.py`, `backend/app/schemas/notification.py`, `backend/app/crud/alert_subscription.py`, `frontend/src/app/settings/notifications/page.jsx`, `backend/tests/test_alert_delivery.py`, `backend/tests/test_notify_database.py`, `backend/tests/test_alert_crud.py`, `backend/tests/test_alert_vocabulary.py`, `backend/tests/test_status_constraints.py`.

### 14 Alert subscription lifecycle

Worth exploring, size M. Done in #56. With 12 and 13 done too, the alerts track is finished. Test approach: real Postgres with a fake email sender, through the routes with `TestClient`.

What was wrong
- The preferences route (`notification_preferences.py:84-557`) held logic that belongs in a module. It decided when a verification email was due, kept the one-minute resend window and created the unsubscribe secret. It recorded a request before its email, undid it when the email was not sent, checked verification links and resolved unsubscribe tokens. It ended its transaction with `db.rollback()` before each send.
- In crud, `update_verification_state` took 8 parameters, three of them compare-and-set guards. All five callers were in the route, and each passed a different mix. It also let a verified address go back to unverified or failed, which no code did.
- The SHA-256 hash pattern was defined three times: in crud and in both token modules. The HMAC key and the base64url signer were written twice, and the route hashed raw tokens in two places. Links were built in two places: alert delivery's `_links` (12 moved it there from notify) and the route's `_send_verification_email`.
- Email addresses were compared in two forms: the route's `strip().lower()` and crud's `email_validator` form (ASCII domain, lower case). The two agree for ASCII addresses. Sign-up keeps an internationalised domain in Unicode, so for such an address every save looked like an address change. It sent the pending verification email again inside the one-minute window. An address `email_validator` refuses, such as one with a non-ASCII name before the @, made the save raise an unhandled `ValueError`.
- `test_notification_preferences.py` called the route functions with `MagicMock` sessions. It patched crud functions and the private `_send_verification_email` and `_load_preferences`, checked call order and read `main.py` as text. Nothing ran the lifecycle on a real database.

What was built

The alert subscription module, `app/services/alert_subscriptions.py`, owns an investor's opt-in to alerts. `read` gives the investor's `AlertPreferences`. Before anything is saved, alerts are off with the default rule. `save` stores the rule. When alerts are turned on and a verification is due, it records a verification request and emails the link. A new or changed address is due at once, and an unverified one at most once a minute. `save` returns `Saved`, which carries the raw unsubscribe token on the first enable only. `request_verification` sends a new link at most once a minute. `confirm` accepts only the newest request's link, within `ALERT_VERIFICATION_TOKEN_TTL_HOURS`, and not once that request is marked failed. Opening the link again once the address is verified changes nothing. `unsubscribe` takes a raw or signed token and never says whether it matched.

Each operation commits what it writes. One that sends an email commits its request and ends its transaction before it calls the sender. So no transaction or row lock is held while the email service answers, and another request already sees the new request. An email that is not sent marks its request failed. Refusals are `AlertSubscriptionError` kinds:
- `AlertsSwitchedOff`;
- `AlertsNotEnabled`;
- `VerificationRequestedRecently`, with the seconds to wait;
- `PreferencesChangedConcurrently`;
- `VerificationEmailNotSent`, with the sender's outcome;
- `InvalidVerificationLink`;
- `SupersededVerificationLink`;
- `AddressNotUsable`.

Each route is one call. `_refusals_answered` turns a refusal into its HTTP answer through `_REFUSALS` and 13's `_UNSENT_VERIFICATION`.

`alert_links` gives alert delivery the news and unsubscribe links of an alert email. The private `_frontend_url` builds every link to the website from `FRONTEND_BASE_URL`, the verification link too. No `SiteUrl` setting is needed, because deploy already sets `FrontendBaseUrl` to the custom domain.

`app/services/alert_tokens.py` holds one hash pattern (`is_token_hash`), one signing key and one signer. It also holds `new_unsubscribe_secret`, `hash_token`, and the v1 unsubscribe and v1c verification tokens. Both formats are unchanged, so links in emails already sent keep working.

In crud, `reserve_verification`, `fail_verification` and `confirm_verification` replace `update_verification_state`. They share one private compare-and-set on the address, the status and the request time. `reserve_verification` writes only while the row still holds the `VerificationState` the caller read, and it refuses a verified address, so a verified address cannot be reserved again. `fail_verification` and `confirm_verification` write only while the request they finish is still pending, at its address and request time. crud's `normalise_email` gives the one form an alert address is stored and compared in. `email_sender.mailbox` applies the same `email_validator` rules but keeps the case, because it checks an address for sending.

Done in Phase 0
- #59 sets `FrontendBaseUrl` to `https://$SITE_DOMAIN_NAME` when that variable is set, so alert and verification links already used the custom domain. The old step 3's "prefer `SiteUrl`" was therefore done. 16's release module works the value out the same way: `https://` and `SiteDomainName`, or else the stack's `FrontendUrl` output.

Done in #56
1. Lifecycle scenarios run through `TestClient(main.app)` on Postgres with the recording sender, against the code as 12 left it. `test_alert_tokens.py` pins the exact unsubscribe and verification token strings.
2. `test_notification_preferences.py` is deleted, with `test_alerts.py`'s unsubscribe test and `test_alert_crud.py`'s SQL-text unsubscribe test. The scenarios cover each behaviour they checked.
3. The alert subscription module holds the state machine, the resend window and the undo. The route maps refusals through one handler. crud's three verification changes replace `update_verification_state`, and `backend/app/crud/README.md` now describes `alert_subscription.py`.
4. `alert_tokens.py` replaces `verification_tokens.py` and `unsubscribe_tokens.py`, and crud uses its `is_token_hash` instead of `SHA256_HEX`. `alert_links` replaces alert delivery's `_links`. `README.md` now says `FRONTEND_BASE_URL` is the base of every link in alert and verification emails.
5. crud's `normalise_email` is public. The module puts the account address in that form before every comparison and the upsert. When `email_validator` refuses the address, it raises `AddressNotUsable`, which answers 422. Stored addresses already have this form, so nothing is migrated.
6. Review fixes:
   - Two paths had no scenario, so removing either check left every test green. Scenarios now cover both: a link for a request marked failed answers 400, and a resend whose subscription is deleted while its email goes out answers 409. Each fails when its check is removed.
   - The docstrings of `request_verification`, `confirm` and `InvalidVerificationLink` now list those refusals. The link rule test is named for both kinds of email it checks, and `_frontend_url`'s docstring names both.
   - The crud README now says what each verification change expects to find: `reserve_verification` the state the caller read, the other two the pending request they finish.

Tests
- `test_alert_subscriptions.py` runs the lifecycle through the app on Postgres. An investor enables alerts, verifies with the emailed link and gets an alert from `notify.handler`. They unsubscribe through the alert's link, and the next artifact sends nothing and leaves no ledger row. Other scenarios cover:
  - the defaults;
  - the deployment switch: 503 for enabling or resending, while a save that keeps alerts off still works;
  - the one-time unsubscribe token and its stored hash;
  - one email for two saves within a minute;
  - a resend within a minute, which answers 429 with a Retry-After of 1 to 60 seconds;
  - a resend after the window, after which the old link answers 400;
  - a link past its lifetime, and a link for a request marked failed, which both answer 400;
  - a link sent to an address that was then replaced;
  - every unsubscribe token form, which gets the same answer and disables only its own subscription;
  - which routes need a session (401) and which do not;
  - an internationalised address saved twice, which gets one email;
  - an unusable address, which answers 422 and stores nothing;
  - a resend whose subscription is deleted while its email goes out, which answers 409;
  - every link an alert or verification email carries, which opens a page under `frontend/src/app` that the CloudFront route function serves.
- One test there commits for real. While the email goes out, it checks that a save or a resend has already committed its request and holds no open transaction (it reads `pg_stat_activity`). 13's scenarios for an unsent email, a malformed Brevo setting and a refused resend stay.
- `test_alert_tokens.py` pins both token strings. It holds the round-trip, tamper, expiry and shape tests from `test_verification_tokens.py` and `test_unsubscribe_tokens.py`, which are deleted, and checks that a new unsubscribe secret is stored only as its hash.
- `test_alert_crud.py` runs the new verification changes on Postgres:
  - a link for an old address cannot verify its replacement;
  - a stale request cannot unverify a verified address;
  - a failed request keeps its time, and only the newest request can fail;
  - changing the address resets verification.
  Pure tests check that `normalise_email` is idempotent, only trims and lower-cases an ASCII address, gives an internationalised domain in ASCII and refuses a non-ASCII name before the @. They also check that `reserve_verification` refuses a verified state and a request time without a timezone.
- Deleted:
  - the 11 remaining tests in `test_notification_preferences.py` (its schema test moved to `test_alert_subscriptions.py`);
  - `test_alerts.py::test_unsubscribe_valid_and_invalid_tokens_share_the_public_response`;
  - `test_alert_crud.py::test_disable_subscription_is_guarded_by_id_and_token_hash`, with its session double;
  - `test_alert_crud.py::test_current_state_change_can_downgrade_a_verified_subscription`, because no operation does that any more;
  - the `update_verification_state` cases of `test_alert_crud_validation_needs_no_database`.

Behaviour changes
- An account address with an internationalised domain is compared in its stored ASCII form. Saving preferences within a minute no longer sends the pending verification email again.
- `PUT /notifications/preferences` with an account address `email_validator` refuses, such as one with a non-ASCII name before the @, answers 422 "The email address on your account cannot receive alerts." and stores nothing. It used to fail with an unhandled 500.
- A save sends a verification email only after its request was recorded. Before, a lost reservation sent an email whose link could never work. The save's row lock made that case unreachable, so no answer changes in practice.
- If the subscription disappears while a resend's email goes out, the resend answers 409 "Notification preferences changed concurrently", as a save already did, instead of an unhandled error.
- Stored data, token formats and link paths do not change. There is no migration.

Left over
- Account addresses are still stored as sign-up gives them (`crud/investor.py`, `core/cognito.py`). The module normalises them where they enter alerts, which was the scope here.
- The default threshold that GET shows still comes from `settings.ALERT_DEFAULT_MIN_CONFIDENCE`, now read in `alert_subscriptions._preferences`. The schema and model defaults use `DEFAULT_ALERT_MIN_CONFIDENCE`. 17 kept the setting and takes its default from that constant, so the two differ only when a deployment sets it. Reading the constant in `_preferences` instead would let the setting, its `.env.example` line, its README row and its configuration-test lines go.
- As decided, the raw-token form of `POST /notifications/unsubscribe` and the one-time `unsubscribe_token` in the PUT response stay. No client reads the token.
- The settings page still shows raw last-delivery codes such as `preferences_changed` (see 12).
- `save` raises `PreferencesChangedConcurrently` if its reservation loses. The upsert's row lock makes that unreachable today. The check keeps the rule that an email goes out only for a recorded request.
- Not checked locally: one real verification email and one real alert through Brevo on staging, opened from a real inbox, with both emails linking to the custom domain (shared with 13's Left over). Optionally, run `SELECT count(*) FROM alert_subscriptions s JOIN investors i ON i.id = s.investor_id WHERE s.email <> lower(trim(i.email))` on staging. It counts the subscriptions whose address has an internationalised domain or no longer matches the account.

Where the code is: `backend/app/services/alert_subscriptions.py`, `backend/app/services/alert_tokens.py`, `backend/app/crud/alert_subscription.py:22-39` (`normalise_email`) and `:175-318` (`VerificationState` and the three verification changes), `backend/app/api/routes/notification_preferences.py`, `backend/app/services/alert_delivery.py:441` (`_compose` asks `alert_links`), `backend/tests/test_alert_subscriptions.py`, `backend/tests/test_alert_tokens.py`, `backend/tests/test_alert_crud.py`.

## Deploy and configuration track

### 16 Release parameters

Strong, size M. Done in #56. Unblocks 18. Test approach: a service we own. Every AWS read goes through an `Aws` port that tests replace with a fake account that records each call, and `apply --dry-run` prints the deploy without calling AWS.

What was wrong
- `deploy-staging.yml` wrote each switch and limit 7 to 8 times: the dispatch input (whose default copied the template default), the AUTO_* and MANUAL_* mappings, the dispatch and push assignments, the validation, the GITHUB_ENV export and the `sam deploy` override. The push path's fallbacks copied the template defaults again.
- The function-to-ECR map was repeated in the deploy workflow, the rollback workflow and three `infra/README.md` copies. Since #59 the rollback no longer listed parameters, but it still repeated the 7-function map. The README copies mapped only 6 of the 7 image functions, so SAM would refuse them, and they left out 11 parameters.
- The `describe-stacks … Outputs` query appeared 21 times: 16 in workflows (deploy-staging 7, publish-staging-frontend 5, execute-staging-change-set 2, rollback-staging-frontend 2) and 5 in `infra/README.md`, one of them reading the OIDC stack. The workflows also read stack Parameters 4 times and StackStatus once.
- A bad value (a limit out of range, a malformed email, a broken Rule) failed only at CreateChangeSet, after the images were built. Only the AuthProvider and true/false checks ran early. The Brevo and Marketaux secret checks were two hand-written bash preflights.
- A brand-new stack could not be planned unless `vars.SITE_DOMAIN_NAME` was set, and the push path failed again at "Capture the previous release". `FrontendBaseUrl` cannot be worked out in the template: ApiFunction would refer to FrontendDistribution, whose API origin refers to ServerlessHttpApi, whose routes refer back to ApiFunction.
- A manual change set reset every switch nobody chose to its template default, for example AuthProvider back to legacy. #59 had fixed the same silent reset in the rollback.
- The schema-drift script had three copies. `validate-branch.yml` and `validate-staging-release.yml` dropped `artifacts.is_duplicate` and `artifact_summaries.prompt_version`. `deploy-staging.yml` dropped only `is_duplicate`, because `a7dd2c6` missed it.

What was built

The release module, `backend/tools/release.py`, run as `python -m tools.release` from `backend/`. It is the only place that knows how a deploy is put together. `plan` writes a release plan: a value for every template parameter, taken from `--set`, then `--set-unless-empty` (where an empty value or `keep` means not given), then the live stack, then the template default. A parameter with no value anywhere is refused. The image parameters always point at the release SHA in this account's ECR repositories, and a release works out `FrontendBaseUrl`. Before any image is built, the plan checks every value against the template's constraints and Rules, checks that each gated secret whose switch is on exists as a SecureString, and checks that the template fits SAM's 51,200-byte inline limit once `sam deploy` packages it. SAM checks the packaged file, not the source: it adds `Metadata: SamResourceId` to every resource and writes the template out again without comments. `packaged_template()` writes the same text with PyYAML, byte for byte what SAM CLI 1.165.0 writes: 46,722 bytes today, from a 42,682-byte source. The plan prints a table of each value, its source and what it replaces to the log and the job summary, and the workflows read its registry and previous release SHA from the step outputs. `apply` checks that the template is unchanged, that the stack is as the plan found it and that the release images exist. It then runs the one `sam deploy` command the plan describes, or only prints it with `--dry-run`. A rollback is a plan that keeps every live value and swaps only the images. `outputs` and `previous-release` read the stack with one call each. A new stack is only created, and a live custom domain only removed, through a reviewed change set, so `--execute` refuses both. `AwsCli` is the real adapter behind the `Aws` port. The module needs only PyYAML, so the queue-wiring CI job runs its tests.

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
- The `github-oidc.yaml` text checks, the CI lint and the deploy role work belonged to 18, which did them in #56. Its rule tests check the roles against `CLOUDFORMATION_ROLE_NAME`, `IMAGE_REPOSITORIES` and `gated_secrets()`.

Where the code is: `backend/tools/release.py`, `backend/tools/template_model.py`, `backend/tools/sync_tickers.py`, `backend/scripts/reproduce_deployed_schema_drift.py`, `.github/workflows/deploy-staging.yml`, `.github/workflows/prepare-staging-backend-rollback.yml`, `.github/workflows/execute-staging-change-set.yml`, `.github/workflows/validate-branch.yml`, `.github/workflows/validate-staging-release.yml`, `.github/workflows/ci-infra-queue-wiring.yml`, `infra/README.md`, `deployment.md`, `devops-processes.md`, `backend/tests/test_release.py`, `backend/tests/test_template_model.py`, `backend/tests/test_deployment_contracts.py`.

### 17 Runtime configuration

Worth exploring, size M to L. Done in #56. Needs 15. Test approach: a service we own. SSM sits behind a `ParameterStore` interface with an SSM adapter and an in-memory one. Configuration tests build settings from plain dicts, and template rules check `infra/template.yaml` against the declarations.

What was wrong
- `Settings` was built when `app.core.config` was first imported, so SSM secrets had to be loaded before anything imported it. Only comments stated that rule, in `lambdas/common.py`, `lambda_api.py`, `lambdas/notify.py`, `lambdas/schedule.py`, `lambdas/public_discussion_schedule.py`, `lambdas/pipeline_stage.py` and `lambdas/artifact_analysis.py`. One test compared where lines sat in `notify.py`, and a subprocess test checked that importing the analysis handler loaded no configuration.
- `load_runtime_configuration` hard-coded six SSM-backed values and wrote them into `os.environ`, where discovery's Chromium inherited the database URL. Nothing tied the six names to the template.
- Code outside `Settings`, mostly in the Lambdas, read 17 more variables itself, and each reader handled bad input its own way. 15 had their own `os.getenv` defaults. `DOWNLOAD_QUEUE_URL` and `RAW_DOCUMENT_BUCKET` had none, and their `os.environ[...]` reads raised `KeyError` when they were missing. The two schedule limits fell back to 10 on a value that was not a whole number and were clamped to 1 to 25. The discovery limits were raised to 1 but failed on a value that was not a whole number. The byte, page and OCR limits failed only when used. The search query was cut to 100 characters, and unknown tickers and sources were dropped. (The source-URL override that applied to manual scrapes but not scheduled ones is gone in #56.)
- Defaults drifted. `MAX_PDF_PAGES` was 100 in code and in `.env.example`, while the template has deployed 500 since `01e7b8c`, the same drift #62 fixed for the size limits. `extract_pdf` kept a third copy of the OCR limits, with 20 pages. #62 deleted `NOTIFICATION_QUEUE_URL` from `Settings` as unread, but the analysis worker read it with `os.getenv`. `NOTIFICATIONS_ENABLED` and `DISCOVERY_QUEUE_URL` were each read both through `Settings` and from `os.environ`.
- AnalysisFunction and PublicDiscussionSchedulerFunction could read every parameter under `${ParameterPathPrefix}` but named only 1 and 4 of them. The analysis worker, which reads untrusted PDFs, could read the Brevo key, the Marketaux token and the Reddit credentials.

What was built

`backend/app/core/config.py` is the runtime configuration. Each setting is a field of the `Settings` dataclass, named after its environment variable and declared once with its default and limits (`text`, `flag`, `integer`, `fraction` and `names`). `settings` is a proxy that builds them from the environment the first time any setting is read, and checks the whole set then. A malformed value, or one outside its limits, raises `ConfigurationError`. It is not a `ValueError`, it lists every bad variable with the limit it broke, and it never shows a value; neither does the repr of `Settings` or `settings`. Reading, setting and deleting an attribute of `settings` act on the built settings, so `patch.object`, `patch.multiple` and `monkeypatch.setattr` keep working: the 26 modules that imported `settings` keep their imports, and the 91 test calls that patched it (63 `monkeypatch.setattr`, 23 `patch.object` and 5 `patch.multiple`, in 21 files) did not change. `Settings.from_environment(environ, parameters=...)` builds settings from any mapping and never writes to `os.environ`. `Settings.required(name)` reads a queue URL or a bucket that must be set.

`SECRETS` registers the six secrets: each one's setting, its SSM parameter and `may_be_missing`. A parameter that does not exist reads as empty for a secret that may be missing, which switches its feature off, and is a `ConfigurationError` for the database URL and the Marketaux token. That is separate from gating: the Marketaux token is a gated secret (read only while `MarketauxEnabled` is on) but must exist whenever its variable names it, and the Reddit credentials may be missing although no switch gates them. When `<SETTING>_PARAMETER` names a parameter and `<SETTING>` is not set, the build reads the value through the `ParameterStore` interface, in whatever process builds the settings. `SsmParameterStore` is the AWS adapter and `InMemoryParameterStore` the test one. The queue-wiring CI job imports the configuration, so `app/core/config.py` and what it loads (`app/__init__.py`, `app/core/__init__.py`, `app/alert_vocabulary.py` and `app/sources.py`) need only the standard library, and the job's path filters list all five. boto3 is imported at the first SSM read.

`declared_settings()` exposes each declaration. The template rules in `test_queue_wiring.py` check every function's environment against the declarations and `SECRETS`. Every variable must be declared or name a registered secret, each `*_PARAMETER` must name its secret's parameter, and each secret must be deployed. A function may read only the secrets it names. A literal value must equal the declared default unless the difference is deliberate, and every value a stack parameter allows must be one its setting accepts. That rule tries the parameter's default, allowed values and bounds, and each value of a fixed sample (`PARAMETER_PROBES`: every whole number and half from 0 to 100, a negative number, empty text and a word) that `Parameter.problems` says the stack accepts.

Done in Phase 0
- The 15 unread `Settings` fields and the stale `GROQ_API_KEY_PARAMETER` in `.env.example` are deleted (#65, #62). So is `ALERT_ONE_CLICK_UNSUBSCRIBE_ENABLED` (#62).
- #62 made `lambdas/download_validation.py` the home of the document size limits, matching the template, and made `sentiment.sentiment_input` cap the FinBERT input at `MAX_ANALYSIS_CHARS`. Superseded by 17: both size limits are settings, and `document_size_limit` and `docx_uncompressed_limit` are deleted (step 8).
- `BEDROCK_MAX_OUTPUT_TOKENS` is gone. Each summary kind sets its own output budget (06, #56).
- Side effect of deleting the fields: a malformed `MAX_*` or `DISCOVERY_LOOKBACK_DAYS` value no longer crashed the API at import. Superseded by 17: every setting is checked at the first build, and the API builds at import (`main.py` reads `CORS_ORIGINS`), so a malformed `MAX_*` or `DISCOVERY_LOOKBACK_DAYS` value in the API's environment stops it at import again. In AWS the API's environment holds none of them (see Behaviour changes).

Done in #56
1. `Settings` is built at the first read, behind the `settings` proxy. The 47 existing fields keep their parsing and limits, the `MARKETAUX_API_KEY` alias and the Cognito checks. `ALERT_DEFAULT_MIN_CONFIDENCE` stays, because `alert_subscriptions._preferences` (14) reads it for an investor with no rule, and it now takes its default from `DEFAULT_ALERT_MIN_CONFIDENCE`. The unused re-export in `app/core/__init__.py` is deleted.
2. The build reads the secrets itself, and `load_runtime_configuration` only built the settings until the next step deleted it. Template rules tie every `*_PARAMETER` variable to `SECRETS`. The queue-wiring CI job now runs when the configuration or a module it imports changes. A test imports the configuration with no site-packages and checks the job's path filters against the modules that import loads.
3. The load-before-import rule is gone: `load_runtime_configuration`, its calls, the rule's comments and `noqa` markers, the source-position test and the analysis handler's subprocess test, which checked that `app.core.config` was not imported at all. `lambda_api.py` and `notify.py` import normally, and the analysis module imports generation and the sentiment service at the top. The workers still import the database layer where they use it. `app/database/__init__.py` imports `connection.py`, so importing a model creates the engine; keeping those imports on use leaves the workers' first settings read inside the stage. A subprocess test now checks that importing any of the five worker handlers builds no settings and does not load the engine module.
4. Two template rules check literal values against the declared defaults, and the values each stack parameter allows against the declared limits. AnalysisFunction's `flex` Bedrock tier and ApiFunction's secure session cookie differ on purpose. Review found that `MarketauxPerTickerLimit` and `PublicDiscussionPerSourceLimit` were `Number` parameters, which CloudFormation and the release plan accept as any number from 1 to 25, fractions too, while the settings refuse a fraction. They are now `String` parameters with the pattern `^([1-9]|1[0-9]|2[0-5])$`, like the two alert limit parameters, and the parameter rule's probes catch a `Number` parameter that feeds a whole-number setting.
5. The weekly schedule reads `SCHEDULED_TICKERS`, `MARKETAUX_ENABLED` and `MARKETAUX_PER_TICKER_LIMIT` (1 to 25) from settings, and `DISCOVERY_QUEUE_URL` with `Settings.required`.
6. The public discussion schedule reads its sources, its per-source limit (1 to 25) and its search query (at most 100 characters, `ASX` when empty) from settings.
7. Discovery reads `DISCOVERY_LOOKBACK_DAYS` and `MAX_DOCUMENTS_PER_RUN` (each at least 1), and `DOWNLOAD_QUEUE_URL` with `Settings.required`.
8. Download, the raw document store, the analysis worker and the local loader read `MAX_DOCUMENT_BYTES`, `MAX_DOCX_UNCOMPRESSED_BYTES` and `RAW_DOCUMENT_BUCKET`. `document_size_limit`, `docx_uncompressed_limit` and their constants are deleted.
9. `sentiment.sentiment_input` reads `MAX_ANALYSIS_CHARS` from settings.
10. The analysis worker reads `MAX_PDF_PAGES`, `MAX_OCR_PAGES`, `MAX_OCR_PIXELS_PER_PAGE`, `NOTIFICATIONS_ENABLED` and `NOTIFICATION_QUEUE_URL` from settings. The team decided that `MAX_PDF_PAGES` defaults to 500, as the template deploys. `extract_pdf` drops its own OCR defaults.
11. Every variable is declared once. A template rule fails on a function variable nothing declares. A sweep fails when runtime code outside `config.py` reads the environment, except for the facts AWS sets about the process. A test fails when `.env.example` names a variable nothing declares. The README's environment table lists the moved settings and their limits, and its local setup section points at `config.py` for every variable.
12. The team decided to narrow the grants. AnalysisFunction may read only `database-url`, and PublicDiscussionSchedulerFunction only `database-url`, the two Reddit credentials and the feed URLs. A rule fails when a function may read a secret its environment does not name. ApiFunction names all six and keeps its wildcard. The change set must be reviewed on staging before it is executed.

The team also decided: a bad value is rejected when the settings are built, by the same rule for every setting, with no per-Lambda clamping; the whole `Settings` is checked at its first build; the `MARKETAUX_API_KEY` alias stays as a declared alias; and a secret resolves from SSM in any process that names its parameter.

Tests
- `test_runtime_configuration.py` builds settings from plain dicts. It covers:
  - the defaults and how each kind of value is read;
  - every minimum, maximum, choice, length and non-empty limit, a fractional limit, the alias, the Cognito checks and `Settings.required`;
  - each secret read from its parameter, or not read when it is set, even to an empty value;
  - a missing parameter, for a secret that may be missing and for one that must exist;
  - the SSM adapter against a fake client;
  - the first read resolving a secret;
  - patching through the proxy, and that no repr shows a value;
  - a bad value failing at the first read rather than at import;
  - in a subprocess, that importing the discovery, download, analysis, schedule and public discussion schedule handlers builds no settings and does not load `app.database.connection`. It names the first handler that does.
  It also holds the environment sweep and the `.env.example` check.
- `test_queue_wiring.py` gains six rules, each broken on purpose by at least one breakage: `parameter_variables_name_registered_secrets`, `functions_read_only_the_secrets_they_name`, `registered_secrets_are_deployed`, `template_literals_match_declared_defaults`, `template_parameters_fit_declared_limits` and `template_variables_are_declared`. The parameter rule's breakages lower a default below its limit, put back a `Number` limit parameter and loosen a limit's pattern. Its CI section imports the configuration with no site-packages. `test_release.py` and `test_deployment_contracts.py` now expect the limits' pattern, and the release plan refuses `MarketauxPerTickerLimit=12.5`.
- They replace `test_config_aliases.py` (the private `_first_env`) and `test_document_size_limits.py`. They also replace the SSM tests in `test_notify.py` and `test_document_workers.py`, which patched `boto3.client` and the private loaded flag, the source-position test, and the two schedule tests that called `_enabled_tickers`. The worker import test replaces 08's analysis handler test in `test_artifact_analysis.py`. The clamping checks in `test_schedule.py` and `test_public_discussion_schedule.py` became rejection tests in the configuration. Tests that set a Lambda's variables in the environment now patch `settings`.

Behaviour changes
- Importing `app.core.config` reads no setting. It still loads `backend/.env` into the environment for local runs, without overriding what is set. A bad value fails at the first settings read with `ConfigurationError`, which lists every bad variable, instead of a `ValueError` at import. The API and notify still fail during Lambda init, because they read settings when they are imported.
- Secret values stay in `settings` and are no longer copied into `os.environ`, so discovery's Chromium no longer inherits `DATABASE_URL`.
- Any process resolves a secret from SSM when `<SETTING>_PARAMETER` is set and `<SETTING>` is not, not only the Lambda entry points; for example, `alembic` with `DATABASE_URL_PARAMETER` and AWS credentials. `.env.example` leaves every `*_PARAMETER` empty, so local runs are unaffected. A missing parameter for a secret that must exist is a `ConfigurationError` naming its variable instead of a `ClientError`.
- An out-of-limit or malformed value is rejected instead of clamped or replaced. A `MARKETAUX_PER_TICKER_LIMIT` or `PUBLIC_DISCUSSION_PER_SOURCE_LIMIT` of 999 used to become 25, and `abc` or `12.5` became 10. A `DISCOVERY_LOOKBACK_DAYS` or `MAX_DOCUMENTS_PER_RUN` of 0 used to become 1. A search query over 100 characters used to be cut. The template allows none of these, a fraction included, and the rules check that.
- `MarketauxPerTickerLimit` and `PublicDiscussionPerSourceLimit` must be a whole number from 1 to 25. As `Number` parameters they also took a fraction or a value such as `10.0`. `PublicDiscussionPerSourceLimit=12.5` deployed and the schedule fell back to 10; with the new settings it would have stopped every scheduled run. `MarketauxPerTickerLimit=12.5` already stopped the API at import through `NEWS_FETCH_LIMIT`. The release plan and CloudFormation now refuse both. The release plan reports `MarketauxPerTickerLimit '26' does not match ^([1-9]|1[0-9]|2[0-5])$` instead of `MarketauxPerTickerLimit must be at most 25, not 26`. The deployed values do not change.
- Worker-only settings are checked in every process that builds the settings. A malformed `MAX_PDF_PAGES` in a shared local `backend/.env` now stops the local API at its first settings read. In AWS each function gets only its own variables.
- A missing `DISCOVERY_QUEUE_URL`, `DOWNLOAD_QUEUE_URL` or `RAW_DOCUMENT_BUCKET` raises `ConfigurationError` naming the variable instead of `KeyError`. In discovery and download it is still a retryable failure of the stage.
- `MAX_PDF_PAGES` defaults to 500 instead of 100 for a run that does not set it. The deployed value, and the 100 that `docker-compose.local-pipeline.yml` sets, do not change.
- AnalysisFunction can read only `database-url`, and PublicDiscussionSchedulerFunction only `database-url`, `reddit-client-id`, `reddit-client-secret` and `public-discussion-feed-urls`.

Left over
- Staging checks that need AWS:
  - Review the change set before executing it. Of 17's changes, it should show only AnalysisFunction's and PublicDiscussionSchedulerFunction's `ReadRuntimeParameters` statements and the two limit parameters. Those change from `Number` to `String` with the same values, so they change no function's environment.
  - After the deploy, confirm all seven functions start and resolve their secrets: an API login and a database read, one dry-run alert, one event for each schedule, and one scrape run end to end. Search CloudWatch for `ConfigurationError`, `ParameterNotFound` and `AccessDeniedException`.
  - Optionally, confirm that the discovery Lambda's Chromium environment no longer carries `DATABASE_URL`.
- Run "Infra and queue wiring CI" on GitHub. cfn-lint and `sam validate --lint`, including the two `String` limit parameters, were not run locally. The pytest job was only approximated, with only pytest and PyYAML importable. The Docker test job runs Python 3.11; locally, every changed file was parsed and the configuration built under 3.11.
- A deployment that sets `ALERT_DEFAULT_MIN_CONFIDENCE` shows a threshold that a save without one does not store, because the schema default is the constant. Reading `DEFAULT_ALERT_MIN_CONFIDENCE` in `alert_subscriptions._preferences` instead would let the setting go (see 14's Left over).
- Unknown scheduled tickers and sources are still dropped, not rejected. Rejecting them would make a typo in `ScheduledTickers` fail every weekly run, so it is a team choice.
- The workers import the database layer where they use it. If importing a model did not create the engine, they could import it at the top.
- ApiFunction keeps its `${ParameterPathPrefix}/*` grant and names all six secrets. The least-privilege rule already flags it for any secret registered later that it does not name, but no rule can see a parameter that is not registered. Listing the six would stop ApiFunction reading those; it would not change what the rule catches.
- `NEWS_FETCH_LIMIT` (the API's on-demand fetch) and `MARKETAUX_PER_TICKER_LIMIT` come from the same `MarketauxPerTickerLimit` parameter, but only the scheduler's setting has the 1 to 25 limit.
- The parameter rule's probes are a sample. A pattern that lets in a whole number over 100 that its setting refuses would pass it.
- Nothing fails when a test sets an environment variable for a setting; the module docstring and `backend/app/core/README.md` ask tests to patch `settings` instead.

Where the code is: `backend/app/core/config.py`, `backend/app/core/README.md`, `backend/lambdas/common.py`, `backend/lambda_api.py`, `backend/lambdas/notify.py`, `backend/lambdas/schedule.py`, `backend/lambdas/public_discussion_schedule.py`, `backend/lambdas/pipeline_stage.py`, `backend/lambdas/discovery.py`, `backend/lambdas/download.py`, `backend/lambdas/download_validation.py`, `backend/lambdas/raw_documents.py`, `backend/lambdas/artifact_analysis.py`, `backend/parsing/analysis.py`, `backend/app/services/sentiment.py`, `backend/scripts/populate_local_content.py`, `backend/.env.example`, `README.md` (the environment table and local setup), `infra/template.yaml` (the two `ReadRuntimeParameters` statements and the two limit parameters), `.github/workflows/ci-infra-queue-wiring.yml`, `deployment.md`, `backend/tests/test_runtime_configuration.py`, `backend/tests/test_queue_wiring.py`, `backend/tests/test_release.py`, `backend/tests/test_deployment_contracts.py`.

### 18 OIDC role pair

Speculative, size S to M. Done in #56. Needs 16. Test approach: remote-owned (AWS IAM). The grants are checked offline as rules against the template model, and the OIDC stack's change set is still reviewed by hand.

What was wrong
- `infra/github-oidc.yaml` held two pairs of deploy roles, one for staging and one for an isolated deployment-test workflow. The CloudFormation execution roles (16 and 14 statements) were near-identical. The GitHub roles (12 and 11 statements) differed in 9 statements and the ECR grant by design.
- They had already drifted: only staging had the Route 53 statements. `main`'s test roles were the `5fb9d54` snapshot from the `deployment-test` branch. They allowed `stocks-in-hand-deployment-test-*` stacks, but the branch's workflow creates `stocks-in-hand-depl-test-*`.
- `d04b23b`, then its revert `b7ed1d6`, then the restore `167a23b` all happened within 27 minutes.
- Which grants each workflow needs was not written down anywhere. Four checks looked for a Sid and an ARN fragment in the template text, so a grant on the wrong resource still passed, and nothing said what a role must not do.
- CI installed cfn-lint but linted only `template.yaml`, so the three templates deployed by hand (`github-oidc.yaml`, `bootstrap.yaml` and `domain.yaml`) were never checked.

What was built

The template model reads IAM roles. `TemplateModel.role_statements(logical_id)` returns the statements of a role's inline policies, and each `Statement` keeps its IAM Condition block as `iam_condition`. `Statement.covers(action, arn, values)` says whether a statement allows an action on an ARN once its `${...}`, `!Ref` and `!GetAtt` references are filled in from `values`. Actions match whatever their case, as in IAM. The model refuses what it cannot read instead of reading it as granting nothing: managed policies, a permissions boundary, a Deny statement, NotAction and NotResource, an Effect other than Allow, an Action that is not a list of names, an intrinsic function where the policies, a document, its Statement block or one statement should be, and an answer that depends on a template condition. It reads `!If` only around a whole policy and in a Resource. It does not evaluate IAM conditions, so a test counts a need as met only by a grant with no IAM condition, and a negative rule counts a grant under any condition.

`backend/tests/test_github_oidc.py` uses it to check, one need at a time, what the deploy roles may and may not do for the six workflows that sign in as the GitHub role. It takes the stack, image repositories, secrets, queues and buckets from the workflows, the release module (16) and `infra/template.yaml`, so a change on either side that breaks a need fails a test. The GitHub role's actions must also be in a list in the test, so a new action needs a reviewer to add it there. The deployment-test roles are deleted.

Done in #56
1. CI lints all four infrastructure templates. A cfn-lint warning, such as a misspelled IAM action (W3037), fails the job too. All four pass cfn-lint 1.57.2 locally. The job also runs when `domain.yaml`, `infra/README.md` or one of the four workflows its tests read but did not watch changes.
2. The deploy roles' grants are checked as rules. The four text checks are deleted, and the queue-wiring CI job runs `test_github_oidc.py` with PyYAML only.
3. The team decided the deployment-test stack is not needed. `DeploymentTestCloudFormationExecutionRole`, `GitHubDeploymentTestRole` and their two outputs are deleted, about 300 lines, and the stack's description names the staging deployment only. `docs/adr/0001-remove-the-deployment-test-deploy-roles.md` records the evidence. It also says why the pair was not defined once instead: a nested stack, a second parameterised stack or `Fn::ForEach` would each cost more than they save here.
4. Review fixes. The model matched actions case for case, and read a Deny and an `!If` around a statement, a Statement block or a PolicyDocument as granting nothing, so a widened role passed every rule. It now matches actions as IAM does and refuses those shapes. A need now asks for a grant with no IAM condition. The secret rule checks every SSM action that returns a value, and the image rule every action that deletes an image or a repository or changes the settings that keep images. The GitHub role's actions are checked against a list. The secret test no longer says the role cannot decrypt the two secrets, because it can (see Left over).

Tests
- `test_github_oidc.py` holds one test per need. Only staging jobs can sign in as the GitHub role. It changes only the staging stack, only through the execution role, and can pass no other role. It pushes every release image, and cannot delete an image or a repository or change the lifecycle policy, tag mutability or repository policy that keep them. It can read exactly the secrets behind a switch, and no other parameter the application reads, such as the database URL, through any of the four SSM actions that return a value. GetParametersByPath is checked on the prefix and every path above it, because AWS allows or refuses it on the path asked for. It reads only the application's queue attributes. It publishes the frontend but cannot touch raw documents. The execution role can change the custom domain's records and poll each change, and `CLOUDFORMATION_ROLE_NAME` names it. The stack defines only the OIDC provider and the two staging roles, so no other resource can grant more than these tests check. The GitHub role grants no action outside the test's list, and a wildcard such as `ecr:*` counts as a new action.
- Before review, 16 broken copies of the template (not kept in the repo) each failed a test. After review, 29 copies were run and each fails a test. 19 of them passed the first version of these tests, for example `ecr:batchdeleteimage`, `kms:decrypt` or `SSM:GetParameter` written in another case, a statement, Statement block, Effect or PolicyDocument under `!If`, a Deny on `ecr:PutImage`, a permissions boundary, an IP condition on the push grant, GetParameters, GetParameterHistory or GetParametersByPath reaching the database URL, and `ecr:DeleteRepository`, `ecr:PutLifecyclePolicy` or `ecr:PutImageTagMutability`.
- It replaces `test_github_oidc_can_check_brevo_parameter_metadata`, `test_cloudformation_role_can_poll_route53_dns_changes` and the OIDC lines of `test_marketaux_is_ssm_backed_bounded_and_release_gated` in `test_deployment_contracts.py`, and `test_staging_github_role_can_read_only_application_queue_attributes` in `test_queue_wiring.py`.
- `test_template_model.py` covers `role_statements`, `iam_condition` and `covers` on an inline template. Each shape the model refuses is a test case, with one for a function's Deny, and a mixed-case grant is read as IAM reads it.
- `test_queue_ci_lints_every_template_and_runs_when_one_changes` replaces the text check of the CI path filters. Every `infra/*.yaml` is linted, the push and pull request filters match, and they watch every template and every test file the job runs.

Behaviour changes
- CI lints `github-oidc.yaml`, `bootstrap.yaml` and `domain.yaml`, and a cfn-lint warning in any of them fails the job.
- SAM function policies are read the same way. `Function.statements` matches actions whatever their case, reads a Statement block that is one object, and raises on NotAction, NotResource, a Deny, an Effect or Action it cannot read, or an intrinsic where a document, its Statement block or a statement should be. `infra/template.yaml` uses none of these, so no queue-wiring or deployment-contract result changes. A function's managed policy names and SAM policy templates are still skipped.
- Nothing changes in AWS until someone redeploys the OIDC stack by hand. That deploy deletes the `stocks-in-hand-github-deployment-test` and `stocks-in-hand-cloudformation-deployment-test-execution` roles and their outputs, if the stack has them, and `vars.AWS_DEPLOY_TEST_ROLE_ARN` then stops working. `infra/README.md` §10 now says to create that change set without executing it and review it first: it may remove only those two roles and two outputs. The comment added above the SSM statements in `github-oidc.yaml` changes no resource.

Left over
- Deploy the OIDC stack after reviewing its change set (`infra/README.md` §10), then run a staging workflow to confirm `stocks-in-hand-github-staging` still works. Delete `AWS_DEPLOY_TEST_ROLE_ARN` from GitHub if it is set.
- Remove anything a deployment-test run left in the account, such as `stocks-in-hand-depl-test-*` stacks, `/stocks-in-hand/deployment-test/*` SSM parameters or `stocks-in-hand-deployment-test-*` ECR repositories, and decide what happens to the `origin/deployment-test` branch.
- The GitHub role can read the Brevo and Marketaux secrets' values, not only their type. Both use the AWS managed `aws/ssm` key, which lets every principal in the account decrypt through SSM, and the role has `ssm:GetParameter` on both. Only the release plan's check is metadata only. Denying `kms:Decrypt` to the role, or moving the two secrets to a customer managed key, would stop this. Both change what is deployed, and the model would need to read a Deny for the first, so the team should decide. Neither closes every path: through the execution role, a staging job can already deploy code that reads any secret.
- cfn-lint on the three newly linted templates was checked locally only. Watch the first CI run.
- IAM Access Analyzer and cfn-policy-validator need AWS credentials, so neither runs here. cfn-lint does not check what an ARN pattern matches, which is why the rule tests do. The rule tests read only the roles' own policies, not the bucket, repository or KMS key policies that can also grant or deny access.
- The execution role's `role/stocks-in-hand-*` grant (`iam:PutRolePolicy` and similar) also matches the OIDC stack's own roles, so a change set could attach a policy to `stocks-in-hand-github-staging`. A permissions boundary would close this.
- `role_statements` does not read a separate policy resource that names a role. The stack test keeps the OIDC stack free of them.
- The execution role's actions are not checked against a list as the GitHub role's are. They follow the application's resources, and its IAM grant already lets a change set do almost anything.

Where the code is: `infra/github-oidc.yaml`, `backend/tools/template_model.py` (`Statement`, `TemplateModel.role_statements`), `backend/tests/test_github_oidc.py`, `backend/tests/test_template_model.py`, `backend/tests/test_queue_wiring.py`, `.github/workflows/ci-infra-queue-wiring.yml`, `infra/README.md` §10, `docs/adr/0001-remove-the-deployment-test-deploy-roles.md`, and `deployment-test.yml` on the `origin/deployment-test` branch.

## Checks before and after merging #56

None of these could run locally: each needs staging, AWS or a GitHub Actions run. They come from the candidates' Left over lists, which have the detail. A push to `main` deploys staging straight away, so merging #56 starts its first release, and the first group has to come before the merge. The `staging` environment accepts only `main` today, so the two workflow runs from a branch need it to accept that branch while they run.

Before merging
- "Validate branch" passes on the PR. Its backend job runs the schema-drift script. Its Docker job, the only run on Python 3.11 with torch installed, mounts `frontend/` and `infra/` for the tests that read them ([08](#08-artifact-analysis), [10](#10-ticker-read-models), [12](#12-alert-delivery), [13](#13-email-sender-port), [14](#14-alert-subscription-lifecycle), [16](#16-release-parameters)).
- "Infra and queue wiring CI" passes on the PR. Its cfn-lint and `sam validate --lint` have not yet seen 17's template change ([17](#17-runtime-configuration), [18](#18-oidc-role-pair)).
- Run the #59 "Prepare staging backend rollback" once from `bugfix/release_workflow_parameters`. It only creates a change set, which should change only the three image URIs ([Phase 0](#left-over-from-phase-0), [16](#16-release-parameters)).
- Run "Deploy staging release" by hand from the PR branch with every input at `keep`, which only creates a change set. Against a stack that runs `main`, it should change only the images, perhaps `FrontendBaseUrl`, the variables 01 and 06 removed, and 17's two `ReadRuntimeParameters` statements and two limit parameters ([16](#16-release-parameters), [17](#17-runtime-configuration)).
- On the current staging stack, search the analysis function's logs for `No module named 'parsing.classification'` ([09](#09-category-taxonomy-ownership)).
- Run `python -m tools.compare_sentiment_buckets` against staging with read-only credentials, and share each ticker's before and after with the team ([10](#10-ticker-read-models)).
- Check that staging has `uq_artifact_summaries_artifact`, which `ON CONFLICT` needs ([07](#07-artifact-summary)).
- Before applying #56's migrations, record the `artifact_type` counts of `asx_announcement` rows ([08](#08-artifact-analysis)) and a dry-run repair's `missing_before` ([07](#07-artifact-summary)).

After the first deploy
- The first push to `main` runs `plan --execute`, `apply`, the health check and, on a failure, the rollback trigger. Then run the module's "Prepare staging backend rollback" and compare it with the #59 change set, and run "Execute approved staging change set" once ([16](#16-release-parameters)).
- Run the `86d9artifacttypes` backfill again now that the new analysis image is live, and compare the counts with the first reading ([08](#08-artifact-analysis)).
- Run the `86d9engagement` backfill's UPDATE again by hand now that the new API image is live, so the posts `main`'s collectors stored after the migration get an engagement ([05](#05-public-discussion-collector)).
- All seven functions start and resolve their secrets: an API login and a database read, one dry-run alert, one event for each schedule and one scrape run end to end. CloudWatch shows no `ImportError`, `ConfigurationError`, `ParameterNotFound` or `AccessDeniedException` ([09](#09-category-taxonomy-ownership), [10](#10-ticker-read-models), [17](#17-runtime-configuration)).
- One analysis records `model_used`, `prompt_version` and all six summary keys, its log events keep their fields, and a notification still reaches its queue. A dry-run repair gives the same `missing_before` as before ([07](#07-artifact-summary), [08](#08-artifact-analysis)).
- `POST /llm/summarise/artifact/{id}` answers 202 and the worker logs `completed`. `POST /llm/summarise/ticker/{symbol}` with `limit=50` sets off no throttling or dead-letter alarm, and stories from `POST /news/fetch/{symbol}` gain sentiment rows ([08](#08-artifact-analysis)).
- `GET /api/sentiment/BHP` answers, `GET /api/tickers/symbol/BHP/brief` shows a live price, and the watchlist page itself makes two API calls (a fresh load shows three, with AppFrame's `/auth/me`) and shows signals ([10](#10-ticker-read-models)).
- The market feed, home page, source library, research summary and deep dive show the empty-summary states ([07](#07-artifact-summary)).
- With `NotificationsEnabled` on, send one real verification email and one real alert through Brevo, and open both from a real inbox. Their links use the custom domain, verify and unsubscribe work, and a replay sends no second alert ([07](#07-artifact-summary), [12](#12-alert-delivery), [13](#13-email-sender-port), [14](#14-alert-subscription-lifecycle)).
- Run "Verify staging queue wiring" once ([15](#15-template-model)).
- If every status value is in `app/status.py`, validate the three CHECK constraints ([04](#04-scrape-run-lifecycle)). `last_delivery_status` should hold only `DeliveryStatus` values ([12](#12-alert-delivery)).
- No hand-made dashboard or alarm reads the `suppressed` log line's old `rollup` field or the `investor_skipped` event ([12](#12-alert-delivery)).
- Check BHP from staging: record its pages if AWS is not blocked, or give it a new listing ([02](#02-source-adapter-per-company)).
- Deploy the OIDC stack by hand after reviewing its change set, then run a staging workflow. Delete `AWS_DEPLOY_TEST_ROLE_ARN` and any deployment-test leftovers ([18](#18-oidc-role-pair)).
- The `infra/README.md` commands were only planned against a fake account, so check each one the first time it runs ([16](#16-release-parameters)).
- Optional: confirm discovery's Chromium no longer gets `DATABASE_URL` ([17](#17-runtime-configuration)), count subscriptions whose address differs from the account's ([14](#14-alert-subscription-lifecycle)), count legacy summary rows whose artifact has no `about` ([07](#07-artifact-summary)), run IAM Access Analyzer on the deploy roles ([18](#18-oidc-role-pair)) and find Brevo's real send-rate limit ([13](#13-email-sender-port)).

## Decisions still needed

| Decision | Candidate | Status |
|---|---|---|
| Which text FinBERT scores | 08 | Decided: title + raw_text, capped at `MAX_ANALYSIS_CHARS`. Done in #62. In #56 every path that scores an artifact goes through `lambdas/artifact_analysis.py`. |
| Support neutral alerts or remove the option | 12 | Decided: support them end to end. Done in #60. |
| How to handle one-click unsubscribe | 13 | Decided for now: stop sending the header (#62). An API-backed endpoint is optional later and stays out of scope in #56. |
| What the preferences routes answer when the provider refuses a verification email's recipient | 13 | Decided in #56: 422, with a message to check the account email. Unavailable answers 502 and misconfigured 500, and verification is marked failed in every case. |
| Whether live alert sends stay one second apart per Lambda container | 13 | Decided in #56: keep it, through the module-level `ALERT_PACER`, which only alert fan-out uses. A dry run never paces. Brevo's real rate limit is still to be found. |
| Whether to keep the raw-token form of `POST /notifications/unsubscribe` and the one-time `unsubscribe_token` in the PUT response | 14 | Decided in #56: keep both for now. `alert_subscriptions.unsubscribe` accepts both forms, and `save` returns the token on the first enable only. |
| How alert email addresses are normalised | 14 | Decided in #56: one way, with `email_validator` through crud's `normalise_email` (ASCII domain, lower case). Stored addresses already have that form, so there is no migration. An address it refuses answers 422. |
| Whether alert links need a `SiteUrl` setting | 14 | Decided in #56: no. Every link is built from `FRONTEND_BASE_URL` in one place, and deploy sets it to the custom domain (#59, and 16's release module). |
| Whether the unsubscribe (v1) and verification (v1c) token formats may change | 14 | Decided in #56: no. Links in emails already sent depend on them, and golden tests in `test_alert_tokens.py` pin both. |
| Mapping from taxonomy category to sentiment bucket, and whether one artifact may count in several buckets | 10 | Decided on 2026-10-13: 09's proposed table, with one bucket per classified announcement. Executive transcripts count in strategy. Security notifications (Appendix 2A, 3G and 3H) count in no bucket. News and unclassified announcements keep keyword matching. Done in #56. Appendix 2A notices are stored as `UNKNOWN` today, so they still count by keyword (see 10's Left over). |
| What the latest filing signal on the brief and watchlist shows | 10 | Decided on 2026-10-13: the sentiment of the most recently published ASX announcement. Done in #56, ordered by `coalesce(published_at, created_at)`, then by the sentiment's time. |
| Where the category sentiment view finds each artifact's bucket | 10 | Decided in #56: at request time, from the taxonomy the API image now ships. There is no backfill, and a mapping change is one edit. |
| Whether 10 deletes `POST /sentiment/{ticker}` and `GET /artifacts/ticker/{ticker_id}` | 10 | Decided in #56: delete both, in the change that moves the watchlist page. |
| Whether 10 waits for the citation branches | 10 | Decided in #56: no. The brief's sources and clarity and the feed's cards are unchanged. |
| What the brief's "Latest filing" and "Latest type" key numbers describe | 10 | Open. They describe the ticker's newest record of any type, which can be a news story, while the latest filing signal beside them is the newest announcement's. The brief could tell the latest filing, at one more query, or the page could call them the latest record (see 10's Left over). |
| Whether `source_url` on Queue A is authoritative | 04 | Decided in #56: the ticker catalogue is authoritative. The `{TICKER}_SOURCE_URL` override is removed and Queue A records the catalogue's page. |
| How to count a malformed public-discussion post: failure or duplicate | 05 | Decided in #56: a failure. It counts in `items_failed` and its run ends partial. |
| Which meaning `SUPPORTED_TICKERS` keeps, and what the other meaning is renamed to | 01 | Decided in #56: it means "enabled for manual scraping" (the `Settings` field and env var). The analysis worker's copy is gone; it accepts catalogue tickers directly. Revisit if the team wants a different name. |
| When to rename the `/gemini` routes | 06 | Decided in #56: now, to `/llm/...`, with no alias. The frontend never called them. |
| Whether to collapse the two summary stores after the views land | 07 | Decided for now in #56: keep both stores; the artifact summary module hides them. Look again now: 10 moved both readers in #56. If they are collapsed, make the summary row the one store. |
| What a feed card, the brief story and the deep-dive detail show with no summary | 07 | Decided in #56: null everywhere, never placeholder or raw text. The frontend's placeholder lists are deleted. |
| Whether 07 waits for the claim-traceability branches | 07 | Decided in #56: no. The chosen branch adds its field through `SummaryExtension` and the artifact card. |
| Whether to delete `POST /artifact-summaries/` | 07 | Decided in #56: delete it, with its crud functions and `ArtifactSummaryCreate`. |
| Whether the summary repair also takes announcements with no summary row | 07 | Decided in #56: no, keep today's selection. |
| Whether a manual deploy keeps the live value of every input it does not choose | 16 | Decided in #56: yes, every dispatch input defaults to `keep`. |
| Whether the frontend publish and rollback workflows read stack outputs through the release module | 16 | Decided in #56: not for now; they stay in bash. |
| Whether a push may create a brand-new stack | 16 | Decided in #56: no; a new stack is only created through a reviewed change set. |
| Whether the admin summary routes still generate inside the API | 08 | Decided in #56: no. Both `/llm/summarise` routes queue a summary request on the analysis queue and answer 202, with no LLM check first. The ticker route queues at most 50. |
| What `POST /news/fetch` does with the stories it stores | 08 | Decided in #56: it queues every story not yet analysed, so the worker scores and summarises it. It no longer summarises inline. |
| Whether to keep `POST /news/summarise` and `POST /news/sentiment` | 08 | Decided in #56: delete both, with `news_summary.py` and `news_sentiment.py`. |
| How the local loader analyses what it loads | 08 | Decided in #56: ASX documents and news stories are analysed in its own process, through the artifact analysis module, the same way as the worker. Reddit posts are only stored and queued (`queue_stored_text`), so they are analysed only when `ANALYSIS_QUEUE_URL` is set and an analysis worker reads that queue. |
| Whether older announcements get their category's artifact type | 08 | Decided in #56: yes. Migration `86d9artifacttypes` backfills them, and `tools/reclassify_artifacts.py` sets the type on announcement rows only. |
| What to call the analysis message that also carries news | 08 | Decided in #56: rename `PublicDiscussionAnalysisMessage` to `StoredTextAnalysisMessage` now, keeping the wire name `public_discussion_analysis` that queued messages carry. |
| Whether the analysis worker keeps publishing `NotificationMessage` | 08 | Decided in #56: yes, unchanged. |
| Which delivery outcomes the alert settings page reports | 12 | Decided in #56: failed and rejected, with the raw status text. The list is named `DELIVERY_PROBLEM_STATUSES` and a test pins it. Plain-language copy is a separate UI change. |
| Whether the default minimum alert confidence stays configurable | 12, 17 | Decided in #56: `DEFAULT_ALERT_MIN_CONFIDENCE` in `app/alert_vocabulary.py` is the one value. `Settings.ALERT_DEFAULT_MIN_CONFIDENCE` stays, because `alert_subscriptions._preferences` reads it for an investor with no rule, and takes its default from the constant. |
| How a malformed or out-of-limit setting is handled | 17 | Decided in #56: it is rejected when the settings are built, with `ConfigurationError` (not a `ValueError`, and never showing the value), by the same rule for every setting and with no clamping in each Lambda. Unknown scheduled tickers and sources are still dropped; rejecting them is a team choice (see 17's Left over). |
| When settings are checked | 17 | Decided in #56: the whole `Settings`, at its first build. |
| The `MAX_PDF_PAGES` default | 17 | Decided in #56: 500, as the template deploys. |
| Whether AnalysisFunction and PublicDiscussionSchedulerFunction keep wildcard SSM grants | 17 | Decided in #56: no. Each may read only the secrets it names, and a least-privilege rule holds that. ApiFunction keeps its wildcard. Review the staging change set before it is executed. |
| Whether to keep the `MARKETAUX_API_KEY` alias | 17 | Decided in #56: keep it, as a declared alias. |
| Where secrets resolve from SSM | 17 | Decided in #56: in any process, when `<SETTING>_PARAMETER` is set and `<SETTING>` is not. |
| Whether the deployment-test stack is still needed | 18 | Decided on 2026-10-13: no. Done in #56: 18 deleted the two deployment-test roles and their outputs. Nothing on `main` used them, and `docs/adr/0001-remove-the-deployment-test-deploy-roles.md` records the evidence. |
| Whether to stop the GitHub role reading the values of the two gated secrets | 18 | Open. Deny `kms:Decrypt` to the role, or move the Brevo and Marketaux secrets to a customer managed key. Either changes what is deployed (see 18's Left over). |
