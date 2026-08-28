# Production Audit Remediation Plan

## Baseline

- Branch: `akshat/fix-production-audit`
- Base: `origin/main` at `aa02ea0`
- Scope: the production failures and UI defects confirmed against the CloudFront deployment on 24–25 August 2026.
- Constraint: preserve the existing StonksInHand visual identity and current contributor work; do not introduce a wholesale redesign.

## Outcomes

1. Ticker pages never attempt to load FinBERT inside the lightweight API Lambda.
2. Sentiment displays only persisted analysis results and never presents missing data as neutral evidence.
3. Navigation retains the application shell and exposes progressive, local loading states instead of intermediate full pages.
4. Ticker overview data is fetched once per ticker route and shared across Summary, News, and Deep Dive.
5. Public labels describe the underlying data accurately.
6. Empty, unauthenticated, validation, and unknown-route states are actionable and accessible.
7. Every public route has a title, language, keyboard focus treatment, adequate contrast, and mobile-sized controls.
8. Deployment and automated tests catch the FinBERT packaging regression and route-level failures before release.

## Phase 1 — Sentiment and data integrity

### API contract

- Add a read-only ticker sentiment response assembled from `ArtifactSentiment` rows already produced by the analysis worker.
- Group persisted artifact signals into the existing revenue, strategy, risk, dividend, organisational, and user-discussion categories using stored category metadata and deterministic fallback keywords.
- Return explicit `available`, `partial`, or `unavailable` status, nullable label/confidence fields, source counts, and the latest analysis timestamp.
- Keep the API Lambda free of PyTorch, Transformers, and model files.
- Preserve a compatibility path for the existing POST route, but make the normal no-body request read persisted results rather than performing inference. Reject unsupported ad-hoc inference clearly instead of raising a model-loading 500.
- Change the frontend to use the read-only endpoint.

### Metric correctness

- Add an accurately named latest-signal confidence field to the ticker overview response.
- Stop labelling model confidence for one announcement as “Public Sentiment” or “coverage”.
- Keep any legacy response key temporarily for compatibility, but remove it from the UI.

### Regression coverage

- Test the API route without `transformers` installed and assert it reads stored results successfully.
- Test unavailable and partial category states.
- Add an API-container smoke check that verifies the API image does not invoke FinBERT for a ticker read.

## Phase 2 — Persistent navigation and request performance

- Move `AppFrame` into the root layout and derive active navigation from the current pathname.
- Add global metadata, `lang="en-AU"`, a skip link, correct header/main/footer landmarks, and a persistent route announcer.
- Move the shared ticker header, tabs, overview, and aside into the ticker layout.
- Add a combined ticker brief endpoint so quote and artifact work occurs once per ticker load.
- Fetch only tab-specific data inside Summary, News, and Deep Dive.
- Replace `window.location.href` navigation with the Next router.
- Derive search state synchronously from `useSearchParams`; remove the hard-coded BHP intermediate state.
- Add bounded GET request coalescing/caching and retryable local error states.
- Reduce the external quote timeout and retain the existing fallback behaviour so quote failure does not block the rest of the brief.

## Phase 3 — Resilient product states

- Render honest sentiment unavailable/partial states with no neutral default.
- Add empty states for BHP/news feeds, search results, announcements, and deep-dive timelines.
- Redirect unauthenticated watchlist visitors to sign-in with a return URL; do not show mutation controls before identity is known.
- Add client constraints and friendly field-level errors to sign-in/sign-up while retaining server validation.
- Make async errors live-region announcements.
- Add focus trapping, Escape handling, labelled dialog semantics, and focus restoration to the watchlist modal.
- Add announcement pagination/load-more behaviour and the missing Consumer Discretionary filter.
- Remove or convert non-functional bookmark/pill affordances and ensure source actions lead to the specific source.

## Phase 4 — Accessibility, responsive UI, and content

- Restore visible `:focus-visible` treatment for every interactive element.
- Raise low-contrast secondary labels to WCAG AA and provide non-colour state cues.
- Enforce at least 44px mobile interaction targets for navigation, tabs, form controls, filters, and actions.
- Keep current responsive grids while limiting long mobile pages through incremental rendering.
- Correct pluralisation and replace unsupported “verified”/“zero hallucinations” claims with source-aware language.
- Add real About, Terms, and Data Sources pages and remove `href="#"` links.
- Add an application icon and a branded static not-found page.
- Update the CloudFront rewrite function so unsupported static routes resolve to the exported 404 page instead of S3 `AccessDenied`, without rewriting `/api/*` responses.

## Phase 5 — Verification

### Automated

- Backend unit tests for sentiment aggregation, ticker overview semantics, auth error mapping, and empty feeds.
- Frontend lint and production static export.
- Infrastructure template validation and focused rewrite-function tests.
- GitNexus change detection before any commit.

### Browser QA

- Desktop 1440px, tablet 768px, and mobile 375px.
- Home → search → ticker Summary → News → Deep Dive navigation.
- Announcements filters, pagination, empty results, and source links.
- Signed-out watchlist redirect, invalid auth validation, and sign-out.
- Keyboard-only navigation, focus visibility, dialog behaviour, landmarks, titles, and horizontal overflow.
- Network and console audit: no sentiment 500, missing favicon, raw 403 page, or duplicate shared ticker requests.

## Acceptance criteria

- No production ticker view imports or invokes FinBERT in the API Lambda.
- Sentiment failures show `Unavailable`, never `Neutral`.
- The application header and footer remain mounted during client navigation.
- Summary-to-News and News-to-Deep-Dive reuse one overview/aside request.
- BHP’s empty news feed has a useful empty state.
- Unknown public routes show the application 404 page.
- All footer destinations are functional.
- No critical automated accessibility findings on audited public pages.
- Backend tests, frontend lint/build, SAM validation, and GitNexus scope detection pass.

## Explicit non-goals

- Replacing the established visual identity.
- Adding new market-data or social-data providers.
- Creating real user accounts or mutating production data during verification.
- Merging unrelated feature branches wholesale; compatible contributor changes will be preserved or selectively mirrored when they directly resolve an audited issue.

## Implementation record — 25 August 2026

- Completed all five remediation phases on `akshat/fix-production-audit` without deploying or mutating production data.
- Backend verification: 129 tests passed and 14 environment-dependent database tests skipped; focused changed-file mypy passed.
- Frontend verification: the Next.js 15.5.21 production export generated all 29 static pages; npm audit reports zero vulnerabilities after the patched `nanoid` override.
- Infrastructure verification: both `cfn-lint infra/template.yaml` and the CI-equivalent `sam validate --lint --template-file infra/template.yaml` passed.
- UI verification: the Impeccable detector reported no source findings. Browser QA covered all 25 distinct public route shapes at 375px, 768px, and desktop widths with no horizontal overflow, missing H1/main/footer landmarks, generic route titles, or undersized visible controls.
- Stateful browser verification: Summary → News → Deep Dive retained one shared ticker brief request; stored partial sentiment rendered missing categories as unavailable; the watchlist dialog trapped/restored focus and supported Escape; the skip link moved keyboard focus to the main landmark.
- GitNexus change detection reported CRITICAL aggregate breadth (112 indexed symbols and 33 historical execution flows) because the branch intentionally replaces the old request-time sentiment flow and moves the shared route shells. Follow-up upstream impact checks on each public sentiment/ticker/schema/shell/watchlist/announcement target were LOW risk with zero or one direct caller; the deliberately unsupported ad-hoc POST inference path is covered by an explicit 503 contract test.
