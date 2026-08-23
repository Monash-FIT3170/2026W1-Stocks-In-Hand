# Cognito Next Steps

## Current status

The local Cognito implementation is ready for independent review.

The additive Supabase migration and the Cognito foundation were applied on
23 August 2026. No application code, backend image, frontend artifact, or
authentication-mode change was deployed. Nothing has been staged or committed.

The staging API still uses image
`397620883742.dkr.ecr.ap-southeast-2.amazonaws.com/stocks-in-hand-api:44dd641ea1d320c34532482afde222bbb6595050`.
`AUTH_PROVIDER` is unset, so the current application defaults to legacy mode.
The weekly scrape schedule remains disabled.

Live checks confirmed project `juwpjjtsqnwfmdbsidnu` is now at Alembic revision
`86d2cognitoidentity`. The nullable `investors.cognito_sub` column and its valid
unique index exist. The `investors` and `auth_sessions` tables still contain
zero rows. No application rows changed.

The database backup was skipped at the user's explicit direction. This removes
the planned restore point for this migration.

The approved tag-scoped OIDC role update was applied on 23 August 2026. The
OIDC stack is `UPDATE_COMPLETE`, and all deployment-test roles remain intact.

Foundation change set `cognito-foundation-only-20260823141426` rolled back
cleanly after CloudFormation required a separate `TagResource` permission.
The temporary, CloudFormation-only permission was then applied through
`cognito-tag-bootstrap-temp-20260823152817`.

Retry change set `cognito-foundation-only-retry-20260823153244` completed
successfully. It added only the retained Cognito user pool and public app
client. The temporary permission was removed through
`cognito-tag-bootstrap-remove-20260823155246` after creation succeeded.

The live pool is `ap-southeast-2_neDgBaw11`. The public client is
`8nfrmgkttdqse18hi741oikhp`. The client has no secret. Deletion protection is
active, TOTP MFA is enabled and optional, and the pool contains zero users.

Protected Cognito requests now confirm the access token with Cognito `GetUser`.
The frontend uses global sign-out. This lets the API reject a revoked session
instead of trusting its signed JWT until the one-hour token expiry.

The review findings have local fixes:

- investor records and all mutation or model-backed routes require an administrator;
- Cognito administrators must enable TOTP before administrator routes accept them;
- `dual` mode supports an ordered cutover without a frontend and backend mismatch;
- frontend candidates are built once and stored by Git SHA and authentication mode.

These changes still need an independent review and staging proof.

## Recommended next action

Run an independent code and security review. Then build and deploy the tested
Cognito-capable backend image with `AuthProvider=legacy` through a reviewed
change set. Do not switch active authentication yet.

The review should cover:

- Cognito access-token validation;
- profile creation and identity linking;
- administrator checks;
- administrator TOTP enforcement;
- watchlist ownership checks;
- token and secret handling;
- migration safety;
- rollback behavior.

## Remaining work

### 1. Decide how existing accounts will move

Owner: Product and security owners

Choose one staging policy:

- reset staging users and ask them to register in Cognito; or
- approve and audit identity links for existing email addresses.

The current implementation does not link an existing email automatically.
`COGNITO_LINK_EXISTING_BY_EMAIL` defaults to `false`.

Do not copy existing password hashes into Cognito.

Exit gate:

- the migration policy is written and approved;
- every retained account has one expected Cognito identity;
- the administrator migration process is approved.

### 2. Review the local implementation

Owner: Independent code and security reviewers

Review these areas:

- `backend/app/core/cognito.py`;
- `backend/app/api/deps.py`;
- `backend/app/api/routes/auth.py`;
- `backend/app/crud/investor.py`;
- `backend/alembic/versions/86d2cognitoidentity_add_cognito_identity.py`;
- `frontend/src/auth/cognito.js`;
- Cognito account and recovery pages;
- `infra/template.yaml`;
- GitHub release workflows;
- the `legacy` to `dual` to `cognito` cutover order.

Exit gate:

- no unresolved security findings;
- no unapproved changes outside the authentication scope;
- migration and rollback steps are accepted.

### 3. Supabase migration applied

Owner: Database owner

Completed on 23 August 2026:

1. Confirmed the expected parent revision `86d2supabasesecurity`.
2. Confirmed there were no investor accounts, duplicate normalized emails, or orphaned watchlists.
3. Reviewed and applied the additive `cognito_sub` migration through Supabase MCP.
4. Confirmed the nullable column and valid unique index.
5. Confirmed all recorded application row counts stayed unchanged.
6. Confirmed RLS and browser-role restrictions stayed in place.

A restorable backup was not taken because the user explicitly waived it.

Exit gate:

- `86d2cognitoidentity` is the active Alembic head;
- `investors.cognito_sub` exists and is nullable;
- the unique index exists;
- the application can still run in legacy mode.

### 4. GitHub OIDC role update applied

Owner: AWS administrator

The CloudFormation execution role needs permission to manage the Cognito user pool and app client.

Review and apply `infra/github-oidc.yaml` using an approved administrator path.

Current evidence:

- AWS account `397620883742` and both target stacks were verified;
- the live OIDC stack is `UPDATE_COMPLETE`;
- its two deployment-test roles were preserved in the prepared template;
- the first account-wide Cognito policy was not executed;
- the replacement policy requires `Project=StocksInHand` and `Environment=staging` tags;
- IAM Access Analyzer returned no findings for the tag-scoped policy;
- change set `cognito-oidc-tag-scoped-20260823140305` completed successfully;
- the OIDC stack returned to `UPDATE_COMPLETE`;
- the tag-scoped policy was verified on the live execution role;
- IAM simulation allows tagged creation and denies an untagged request;
- all five OIDC stack resources remain `UPDATE_COMPLETE`.

Exit gate:

- the execution role has the reviewed Cognito permissions;
- no broad permissions were added outside the documented statement;
- the deployment role can still create a review-only change set.

### 5. Cognito foundation deployed; backend deployment remains

Owner: AWS deployment owner

The Cognito pool and public client are live. The application code is not.

Create and review the next staging change set with:

```text
AuthProvider=legacy
```

This change set should deploy the tested dual-mode backend while keeping legacy
authentication active. It must not replace the Cognito resources or switch
active authentication.

Foundation evidence:

- change set `cognito-foundation-only-20260823141426` added only `CognitoUserPool` and `CognitoUserPoolClient`;
- it has zero modifications, removals, or replacements;
- the pool has deletion protection, retain policies, and required staging tags;
- the client is public and has no client secret;
- the update failed at `CognitoUserPool` because `cognito-idp:TagResource` was denied;
- CloudFormation completed rollback at `UPDATE_ROLLBACK_COMPLETE`;
- temporary change set `cognito-tag-bootstrap-temp-20260823152817` changed only the execution-role policy, with no role replacement;
- retry change set `cognito-foundation-only-retry-20260823153244` added only `CognitoUserPool` and `CognitoUserPoolClient`;
- the retry completed and the application stack is `UPDATE_COMPLETE`;
- pool `ap-southeast-2_neDgBaw11` has deletion protection and the required staging tags;
- client `8nfrmgkttdqse18hi741oikhp` is public, has no secret, and has token revocation enabled;
- TOTP MFA is enabled in optional mode;
- the pool contained zero users at verification time;
- removal change set `cognito-tag-bootstrap-remove-20260823155246` completed;
- no temporary `Bootstrap*` policy statement remains on the execution role;
- the permanent Cognito permissions remain limited by staging resource tags;
- the current backend image, schedule, and legacy login stayed untouched.

Exit gate:

- [x] the Cognito user pool and public app client exist;
- [x] the app client has no client secret;
- [x] deletion protection and retention controls are active;
- [x] the prior backend image and legacy-default setting stayed unchanged;
- [ ] the tested Cognito-capable backend image is deployed in legacy mode;
- [ ] real staging outputs are used in its configuration;
- [ ] legacy regression tests pass against that image.

### 6. Finish API Gateway route protection

Owner: Backend and infrastructure owners

The JWT authorizer is defined but is not bound to protected routes.
FastAPI currently performs the active token checks.

Add reviewed route bindings for:

- `/api/auth/bootstrap`;
- `/api/auth/me`;
- `/api/watchlists` and child routes;
- `/api/watchlist-tickers` and child routes;
- administrator investor routes;
- scrape and scrape-run routes.

The route design must preserve the approved legacy rollback path.

Exit gate:

- protected routes require a valid Cognito access token in Cognito mode;
- public market-data routes remain public;
- legacy mode remains usable until the cutover gate closes;
- FastAPI still validates authorization after API Gateway accepts a token.

### 7. Complete automated validation

Owner: Test owner

Still required:

- add UI-level tests for page navigation, confirmation resend, and recovery forms;
- run PostgreSQL integration tests against an approved test database;
- record administrator and watchlist-isolation results;
- verify tokens and secrets do not appear in logs;
- run an API image smoke test with real staging Cognito outputs.

Current local evidence:

- backend suite: 107 passed and 14 skipped;
- focused Cognito and route-authorization suites: 36 passed;
- frontend Cognito adapter and token-refresh suites: 12 passed;
- revoked-session and Cognito-outage paths passed focused tests;
- legacy and Cognito static frontend builds passed;
- missing Cognito build settings correctly failed the build;
- npm audit reported zero known vulnerabilities;
- Bandit passed for `backend/app` and `backend/main.py`;
- CloudFormation lint passed for `infra/template.yaml` and `infra/github-oidc.yaml`;
- the local Alembic head is `86d2cognitoidentity`;
- `sam validate --lint --template-file infra/template.yaml` passed;
- edited GitHub workflow files passed YAML syntax checks;
- staging preparation now runs backend tests, Bandit, frontend tests, and builds before cloud changes.

Current live Supabase evidence:

- the remote Alembic revision is `86d2cognitoidentity`;
- `investors.cognito_sub` is nullable `varchar(128)`;
- `ix_investors_cognito_sub` is valid and unique;
- `investors` and `auth_sessions` each contain zero rows;
- all recorded application row counts stayed unchanged;
- duplicate normalized emails and orphaned watchlists both remain zero;
- `anon` and `authenticated` have no direct public-table grants;
- all public tables have RLS enabled;
- security advisors report only informational no-policy notices;
- performance advisors report only informational unused-index notices;
- Supabase recorded migration `20260823030155_add_cognito_identity`;
- no application data rows were written during the migration.

### 8. Prepare the coordinated cutover

Owner: Release owner

Prepare the backend and frontend releases from the same approved Git commit.

Required order:

1. Confirm the database migration and Cognito resources.
2. Run `Prepare staging frontend` for both `legacy` and `cognito`.
3. Confirm both immutable candidates use the approved full Git SHA.
4. Deploy the backend with `AuthProvider=dual`.
5. Publish the prepared Cognito candidate.
6. Verify Cognito signup, login, bootstrap, TOTP, and protected requests.
7. Deploy the backend with `AuthProvider=cognito`.
8. Keep the prepared legacy release for rollback.

Exit gate:

- the backend mode accepts the selected frontend authentication mode;
- the selected Git SHA is recorded;
- rollback owners and commands are recorded;
- required reviewers approve the release.

### 9. Run staging end-to-end tests

Owner: Test reviewer

Use new test email addresses and do not record passwords or tokens.

Test:

- valid signup;
- weak-password rejection;
- duplicate-account handling;
- email confirmation;
- confirmation-code resend and cooldown;
- login and profile bootstrap;
- wrong-password rejection;
- forgotten-password reset;
- access-token refresh;
- page refresh with a valid session;
- logout and old-session rejection;
- watchlist ownership isolation;
- normal-user rejection from administrator routes;
- one bounded administrator scrape;
- one Cognito subject mapping to one Supabase investor.

Exit gate:

- every required staging test passes;
- failures contain no secrets;
- one independent reviewer approves the evidence.

### 10. Promote the first administrator

Owner: Database and security owners

Promote the first administrator only after its verified Cognito identity is linked.
Require that account to finish TOTP setup before testing administrator routes.

Record:

- the investor UUID;
- the Cognito subject;
- the approver;
- the change time;
- the verification result.

Do not put credentials or access tokens in the record.

## Rollback boundary

If the Cognito cutover fails:

1. Set `AUTH_PROVIDER=dual` through a reviewed change set.
2. Restore the approved mode-specific legacy frontend artifact.
3. Verify legacy login and protected requests.
4. Set `AUTH_PROVIDER=legacy` through a reviewed change set.
5. Keep the Cognito user pool for investigation.
6. Do not delete Cognito users automatically.
7. Do not remove `cognito_sub` during an incident.
8. Use a forward migration for later database changes.

## Completion definition

The Cognito change is complete when:

- signup, confirmation, login, reset, refresh, and logout pass in staging;
- protected routes reject invalid or missing access tokens;
- normal users cannot call administrator operations;
- each Cognito subject maps to one Supabase investor;
- Supabase stores no new passwords or custom sessions;
- the reviewed rollback procedure is proven;
- required reviewers approve the recorded evidence.

See `COGNITO_SUPABASE_IMPLEMENTATION_PLAN.md` for the full design and phase details.
