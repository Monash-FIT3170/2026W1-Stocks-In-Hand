# Cognito and Supabase Authentication Implementation Plan

## Implementation status, 23 August 2026

The first implementation slice is complete in the local worktree. The additive
Supabase schema migration and the Cognito foundation were applied on
23 August 2026. The Cognito-capable application code has not been deployed.

Completed locally:

- additive `investors.cognito_sub` migration and unique index;
- Cognito access-token checks and verified profile bootstrap in FastAPI;
- legacy, dual, and Cognito backend modes, with legacy still the default;
- retained Cognito user pool, public app client, and JWT authorizer resources;
- immutable, mode-specific frontend preparation and release workflows;
- Cognito signup, email confirmation, resend, login, password reset, refresh, and logout pages;
- TOTP setup and sign-in challenge support for administrator MFA;
- administrator guards on investor, mutation, model-backed, and scrape routes;
- focused backend tests, static frontend builds, dependency audit, and CloudFormation linting.

Still required before a Cognito cutover:

- review the local code and security controls independently;
- build and deploy the tested backend image in legacy mode;
- bind the API Gateway JWT authorizer to protected routes without breaking legacy rollback;
- test with real staging outputs, Cognito email, and new test users;
- approve the identity-link policy for existing legacy accounts;
- record PostgreSQL integration tests, security review, and staging end-to-end evidence.

Live verification on 23 August 2026 confirmed the target project is
`juwpjjtsqnwfmdbsidnu`. Its Alembic revision is now `86d2cognitoidentity`.
The nullable `investors.cognito_sub` column and its valid unique index exist.
Both account tables remain empty, and no application rows changed. The user
explicitly waived the planned database backup, so no new restore point was made.

The approved tag-scoped OIDC role update was applied on 23 August 2026. The
OIDC stack is `UPDATE_COMPLETE`, all deployment-test roles remain intact, and
IAM simulation denies untagged Cognito pool creation.

Foundation change set `cognito-foundation-only-20260823141426` was executed but
rolled back cleanly. Cognito pool creation failed because CloudFormation also
requires `cognito-idp:TagResource`.

Temporary remediation change set `cognito-tag-bootstrap-temp-20260823152817`
added that permission only for calls through CloudFormation. Retry change set
`cognito-foundation-only-retry-20260823153244` then added only the Cognito user
pool and public app client. It completed successfully, and the application
stack is `UPDATE_COMPLETE`.

Pool `ap-southeast-2_neDgBaw11` has deletion protection, the required staging
tags, optional TOTP MFA, and zero users. Public client
`8nfrmgkttdqse18hi741oikhp` has no secret and has token revocation enabled.
Removal change set `cognito-tag-bootstrap-remove-20260823155246` then removed
the temporary permission. Only the permanent tag-scoped Cognito rules remain.

The staging API still uses the prior image ending in Git SHA
`44dd641ea1d320c34532482afde222bbb6595050`. `AUTH_PROVIDER` is unset and still
defaults to legacy mode. The weekly scrape schedule remains disabled.

## Purpose

Replace the custom PostgreSQL password and session system with Amazon Cognito.
Keep Supabase PostgreSQL as the application database.

This plan records proof for the deployed Cognito foundation. It is not proof
that the Cognito application flow or cutover is deployed.
Each phase has an owner, evidence, an exit gate, and rollback notes.

Plan date: 2026-08-23

## Decision summary

- Amazon Cognito User Pools will own signup, passwords, verification, login, token refresh, and logout.
- Supabase will store investor profiles, watchlists, roles, and application data.
- FastAPI will remain the only service that connects directly to Supabase PostgreSQL.
- The browser will not receive a Supabase database password or service key.
- The existing custom signup and login pages will remain, but they will call Cognito through AWS Amplify Auth.
- Signup will require email confirmation before login completes.
- Cognito will handle forgotten-password and password-reset flows.
- FastAPI will validate Cognito access tokens for every protected request.
- Database roles will remain the source for application authorization during this change.
- Cognito groups are outside this first release.
- Supabase third-party authentication is not required for this design.
- No applied Alembic migration will be edited or replaced.

## Baseline before the local implementation

Before this local slice, the application did not use Cognito.

- `frontend/src/app/sign-up/page.jsx` posts a password to `/auth/sign-up`.
- `frontend/src/app/sign-in/page.jsx` posts a password to `/auth/sign-in`.
- `frontend/src/app/sign-out/page.jsx` deletes a custom backend session.
- `frontend/src/app/components/layout/AppFrame.jsx` stores a local login hint.
- `backend/app/api/routes/auth.py` creates users and sessions in PostgreSQL.
- `backend/app/api/deps.py` authenticates an `HttpOnly` database session cookie.
- `backend/app/core/security.py` hashes passwords and session tokens.
- `backend/app/models/investor.py` stores `hashed_password`.
- `backend/app/models/auth_session.py` stores active sessions.
- `infra/template.yaml` has no Cognito user pool, app client, or JWT authorizer.

The current code can create a working local database account.
It cannot create a Cognito account because no Cognito path exists.

## Target request flow

```text
Signup
Browser -> Cognito SignUp -> verification email -> Cognito ConfirmSignUp

Login
Browser -> Cognito SignIn -> access and refresh tokens

Password recovery
Browser -> Cognito ResetPassword -> email code -> ConfirmResetPassword

Profile setup
Browser -> POST /api/auth/bootstrap with access token
        -> FastAPI validates Cognito token
        -> FastAPI reads verified Cognito attributes
        -> FastAPI creates or links the Supabase investor row

Protected API call
Browser -> Authorization: Bearer <access token>
        -> API Gateway JWT check where a protected route is mapped
        -> FastAPI validates the token again
        -> FastAPI finds investors.cognito_sub
        -> FastAPI checks the existing database role and record ownership
        -> FastAPI reads or writes Supabase
```

## Scope

This plan includes:

- Cognito infrastructure in SAM and CloudFormation;
- custom signup, confirmation, resend, login, logout, and session UI;
- forgotten-password and password-reset UI;
- access-token handling in the static Next.js frontend;
- Cognito JWT verification in FastAPI;
- investor profile linking in Supabase;
- administrator and ownership checks;
- expand and contract database migrations;
- local, CI, staging, security, and rollback checks;
- deletion of the legacy password system after the rollback window.

This plan does not include:

- social login;
- passkeys;
- Cognito Identity Pools or temporary AWS credentials;
- direct browser access to Supabase Data API, Storage, or Realtime;
- production SES setup beyond a release gate;
- migration of real production passwords without a separate approved design.

## Ownership

| Area | Owner | Reviewer |
|---|---|---|
| Cognito and SAM resources | Person 1 | Person 2 |
| Supabase migration and data checks | Person 2 | Person 1 |
| FastAPI token and authorization work | Backend owner | Security reviewer |
| Next.js Cognito flows | Frontend owner | Application reviewer |
| End-to-end test evidence | Test owner | Release reviewer |
| Staging change-set approval | Person 1 | Person 2 executes |

Do not combine implementation, security review, test review, and release approval into one sign-off.

## Gate 0: Confirm migration assumptions

Owner: Product owner and Person 2

Complete these decisions before code changes:

- [ ] Confirm whether the existing database contains real user accounts.
- [ ] Confirm whether those users must keep their existing passwords.
- [ ] Confirm that email is the Cognito login name.
- [ ] Confirm that email verification is required.
- [ ] Confirm the staging frontend URL used in confirmation help text.
- [ ] Confirm whether Cognito's default email sender is acceptable for staging.
- [ ] Confirm the administrator account creation process.
- [ ] Confirm the required rollback window, with seven days as the proposed default.

Recommended staging decision:

- Reset test identities and ask testers to register again in Cognito.
- Do not attempt to copy bcrypt password hashes into Cognito.
- Preserve each investor's internal UUID when linking application data.
- Promote the first administrator only after its verified Cognito identity is linked.

If real users must keep their passwords, stop this plan.
Create a separate Cognito User Migration Lambda design and security review.

Exit gate:

- [ ] The account migration choice is written and approved.
- [ ] No real user is silently locked out.
- [ ] The rollback deadline has a date and owner.

## Phase 1: Record a baseline

Owner: Test owner

Record the current state before editing code:

- [ ] Save the full Git SHA and `git status --short` output.
- [ ] Run the focused backend authentication tests.
- [ ] Run all backend tests against migrated PostgreSQL.
- [ ] Build the static frontend with `NEXT_PUBLIC_API_BASE_URL=/api`.
- [ ] Record the current Alembic head.
- [ ] Record the `investors` and `auth_sessions` row counts without account details.
- [ ] List all routes using `get_current_investor` or `require_admin_investor`.
- [ ] Save the current staging stack outputs and active Lambda image SHA.
- [ ] Save one failed signup response and its matching backend log event.

Do not print passwords, tokens, database URLs, or SSM values in evidence.

Exit gate:

- [ ] Baseline tests have clear pass, fail, or blocked results.
- [ ] Current deployment state is verified from AWS, not assumed from local files.
- [ ] The protected-route inventory is complete.

## Phase 2: Add Cognito infrastructure

Owner: Person 1

### 2.1 Add user pool resources

Update `infra/template.yaml` with these resources:

- `AWS::Cognito::UserPool` named for the environment;
- `AWS::Cognito::UserPoolClient` for the static browser application;
- a JWT authorizer for the existing HTTP API;
- retained outputs for the user pool ID, app client ID, and issuer URL.

Use these user pool controls:

- [ ] Allow email as the sign-in name.
- [ ] Treat email addresses as case-insensitive.
- [ ] Auto-verify email addresses.
- [ ] Recover accounts through verified email only.
- [ ] Set a password policy that matches the UI text and tests.
- [x] Allow software-token MFA and enforce it for Cognito administrators.
- [ ] Enable deletion protection where CloudFormation supports it.
- [ ] Add `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`.
- [ ] Use Cognito's default sender only for low-volume staging tests.
- [ ] Require an approved SES sender before a production release.

Use these app client controls:

- [ ] Set `GenerateSecret: false` because this is a public browser client.
- [ ] Enable SRP-based user authentication.
- [ ] Enable refresh-token authentication.
- [ ] Enable token revocation.
- [ ] Enable user-existence error protection.
- [ ] Confirm access tokens can call Cognito `GetUser`.
- [ ] Keep token lifetimes explicit and documented.
- [ ] Do not enable client credentials or machine-to-machine grants.

Do not add an app client secret to GitHub, SSM, or frontend environment files.

### 2.2 Add backend configuration

Pass these values to the API Lambda:

- `AUTH_PROVIDER=cognito` after the cutover gate;
- `COGNITO_USER_POOL_ID`;
- `COGNITO_APP_CLIENT_ID`;
- `COGNITO_ISSUER`;
- the existing AWS region.

Add matching settings to `backend/app/core/config.py`.
Validate required Cognito settings at API startup when Cognito mode is active.

### 2.3 Add frontend build configuration

Update `.github/workflows/publish-staging-frontend.yml` to read CloudFormation outputs.
Pass only these public build values:

- `NEXT_PUBLIC_AUTH_PROVIDER=cognito`;
- `NEXT_PUBLIC_AWS_REGION`;
- `NEXT_PUBLIC_COGNITO_USER_POOL_ID`;
- `NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID`.

Fail the build if any Cognito value is missing.
Do not use placeholder values in a staging artifact.

### 2.4 Respect the HTTP API proxy constraint

The API currently uses one `ANY /{proxy+}` route.
A default authorizer would also block public market-data routes.

Use two layers:

1. FastAPI token validation remains mandatory on protected dependencies.
2. API Gateway JWT authorization protects each mapped private route as a second check.

Map the known private paths explicitly, including:

- `/api/auth/bootstrap`;
- `/api/auth/me`;
- `/api/watchlists` and child paths;
- `/api/watchlist-tickers` and child paths;
- `/api/investors` and child paths;
- `/api/scrape` and child paths;
- `/api/scrape-runs` and child paths.

Keep the proxy route for public endpoints.
Generate a route inventory from FastAPI OpenAPI during CI.
Fail CI when a protected dependency lacks a matching gateway route.

Exit gate:

- [ ] SAM and CloudFormation validation pass.
- [ ] The app client has no secret.
- [ ] Public routes remain public by design.
- [ ] Private routes have both gateway and FastAPI checks.
- [ ] The user pool is retained during stack rollback or deletion.
- [ ] Person 1 has reviewed the complete change set.

## Phase 3: Expand the Supabase schema

Owner: Person 2

Create a new Alembic migration after `86d2supabasesecurity`.
Suggested revision name: `86d2cognitoidentity`.

The expand migration must:

- [x] Add nullable `investors.cognito_sub` as `String(128)`.
- [x] Add a unique index on `cognito_sub` for non-null values.
- [x] Preserve the existing investor UUID primary key.
- [x] Preserve all watchlist and other foreign keys.
- [x] Leave `hashed_password` in place during the rollback window.
- [x] Leave `auth_sessions` in place during the rollback window.
- [x] Avoid changing existing email values automatically.

Update these files with the new field:

- `backend/app/models/investor.py`;
- `backend/app/schemas/investor.py` where a response needs the value;
- `backend/app/crud/investor.py` with dedicated identity-link functions;
- database model and migration parity tests.

Never return `cognito_sub` from public investor list endpoints unless required.
Never allow a normal profile update request to change it.

Before applying the migration:

- [ ] Take a Supabase backup. Skipped at the user's explicit direction.
- [x] Confirm the current Alembic revision.
- [x] Check for duplicate case-insensitive emails.
- [x] Check for orphaned watchlists.
- [x] Apply the migration with the approved Supabase MCP connection.
- [x] Confirm the Lambda transaction pooler is not used for Alembic.

Exit gate:

- [ ] The migration passes on a clean PostgreSQL database.
- [ ] The migration passes on a copy of the staging schema.
- [x] Existing application data remains linked to the same investor UUIDs.
- [x] Legacy login still works before the cutover flag changes.

## Phase 4: Implement FastAPI Cognito authentication

Owner: Backend owner

### 4.1 Add a token verifier

Create `backend/app/core/cognito.py`.
Add a pinned JWT library with cryptographic support to `requirements-api.txt`.

The verifier must:

- [ ] Read the bearer token from the `Authorization` header.
- [ ] Accept only Cognito access tokens.
- [ ] Verify the RS256 signature against the user pool JWKS.
- [ ] Verify `iss`, `exp`, `iat`, `token_use`, and `client_id`.
- [ ] Reject ID tokens at API authorization boundaries.
- [ ] Cache signing keys with a bounded lifetime.
- [ ] refresh the key set once when a known key is not found.
- [ ] Fail closed when Cognito or JWKS data is unavailable.
- [ ] Return stable internal error codes without exposing token data.

Never log bearer tokens, refresh tokens, authorization headers, or JWT bodies.

### 4.2 Replace the authentication dependency

Update `backend/app/api/deps.py`.

The new `get_current_investor` must:

- [ ] validate the Cognito access token;
- [ ] read the stable `sub` claim;
- [ ] find the investor by `cognito_sub`;
- [ ] return `401` for an invalid token;
- [ ] return a clear profile-setup error when no investor link exists;
- [ ] retain current record-ownership checks;
- [ ] retain the database `role` check for administrator routes.

Do not trust email, role, investor ID, or Cognito subject values from request bodies.

### 4.3 Add idempotent profile bootstrap

Replace custom signup behavior with `POST /auth/bootstrap`.

The endpoint must:

- [ ] require a valid Cognito access token;
- [ ] call Cognito `GetUser` with that access token;
- [ ] read verified `sub`, email, and name attributes;
- [ ] require `email_verified=true` before creating or linking a profile;
- [ ] normalize the email before lookup;
- [ ] link one existing staging investor only under an approved migration rule;
- [ ] otherwise create a new investor with role `user`;
- [ ] handle repeat calls without duplicate rows;
- [ ] handle concurrent first-login calls safely;
- [ ] never accept `role` from the client;
- [ ] return the existing `InvestorResponse` shape where practical.

Keep `GET /auth/me`, but make it token-based.
Remove backend password handling from the active Cognito path.

### 4.4 Provide a controlled compatibility switch

Use `AUTH_PROVIDER=legacy` or `AUTH_PROVIDER=cognito`.
The active provider must come from runtime configuration, not a Git branch.

During the rollback window:

- [ ] keep legacy route code available only in legacy mode;
- [ ] return `404` or `410` from legacy signup and login in Cognito mode;
- [ ] prevent both providers from creating accounts at the same time;
- [ ] mark every authentication log event with the provider name;
- [ ] keep secrets and user details out of logs.

Exit gate:

- [ ] Valid Cognito access tokens reach protected endpoints.
- [ ] ID tokens and malformed tokens are rejected.
- [ ] A Cognito user links to exactly one investor UUID.
- [ ] A normal user cannot gain the administrator role.
- [ ] Watchlist ownership tests still pass.
- [ ] Cost-bearing scrape routes still require an administrator.

## Phase 5: Implement the frontend Cognito flow

Owner: Frontend owner

### 5.1 Add and configure Amplify Auth

Add a pinned AWS Amplify dependency.
Create `frontend/src/app/lib/auth.js`.

The module must:

- [ ] configure Cognito once in the browser;
- [ ] expose signup, confirmation, resend, login, password reset, logout, and session helpers;
- [ ] fail clearly when required build values are absent;
- [ ] avoid printing tokens in errors or browser logs;
- [ ] avoid any Cognito client secret.
- [ ] avoid copying Cognito tokens into custom local-storage keys.

### 5.2 Change signup

Update `frontend/src/app/sign-up/page.jsx`.

- [ ] Call Cognito `signUp` instead of `/auth/sign-up`.
- [ ] Send `email` and `name` as Cognito attributes.
- [ ] Follow the CloudFormation password policy.
- [ ] Redirect unconfirmed users to `/confirm-sign-up`.
- [ ] Handle duplicate users, invalid passwords, rate limits, and network errors.
- [ ] Do not mark the browser as signed in after signup alone.

Create `frontend/src/app/confirm-sign-up/page.jsx`.

- [ ] Accept the confirmation code.
- [ ] Support resending the code with a visible cooldown.
- [ ] Avoid revealing whether an unrelated email is registered.
- [ ] Send confirmed users to login.

### 5.3 Change login and profile bootstrap

Update `frontend/src/app/sign-in/page.jsx`.

- [ ] Sign in through Cognito.
- [ ] Handle unconfirmed accounts by offering confirmation.
- [ ] Call `/auth/bootstrap` after the first successful sign-in.
- [ ] Continue to `/watchlist` only after bootstrap succeeds.
- [ ] Show a recovery path for expired or invalid sessions.

### 5.4 Add password recovery

Create `frontend/src/app/forgot-password/page.jsx`.
Create `frontend/src/app/reset-password/page.jsx` if the flow uses separate pages.

- [ ] Start password recovery through Cognito.
- [ ] Accept the emailed confirmation code and new password.
- [ ] Support requesting a new code with a visible cooldown.
- [ ] Apply the same password rules used during signup.
- [ ] Avoid revealing whether an unrelated account exists.
- [ ] Send the user to login after a successful reset.

### 5.5 Change API requests

Update `frontend/src/app/lib/api.js`.

- [ ] Obtain the current Cognito access token before a protected request.
- [ ] Add `Authorization: Bearer <token>`.
- [ ] Refresh through Amplify when the session can be refreshed.
- [ ] Retry at most once after an authentication failure.
- [ ] Do not attach tokens to non-API origins.
- [ ] Clear the local session state after a final `401`.

Keep public API calls usable without a token.

### 5.6 Change session and logout UI

Update these files:

- `frontend/src/app/components/layout/AppFrame.jsx`;
- `frontend/src/app/sign-out/page.jsx`;
- `frontend/src/app/watchlist/page.jsx`.

Remove `stonks_signed_in` as the source of truth.
Derive the visible session from Amplify and `/auth/me`.
Use Cognito logout and clear only the current app's cached state.

Exit gate:

- [ ] Signup sends a confirmation code.
- [ ] Confirmation activates the user.
- [ ] Login obtains a refreshable session.
- [ ] Logout blocks later protected requests.
- [ ] A page refresh preserves a valid session.
- [ ] Expired sessions return the user to login without a loop.
- [ ] No token appears in the URL, UI, or application logs.

## Phase 6: Tests and release gates

Owner: Test owner

### 6.1 Backend tests

Add focused tests for:

- [ ] valid access-token claims;
- [ ] expired tokens;
- [ ] wrong issuer;
- [ ] wrong app client;
- [ ] wrong `token_use`;
- [ ] unknown signing key;
- [ ] malformed authorization headers;
- [ ] JWKS refresh and cache behavior;
- [ ] missing investor profile;
- [ ] idempotent profile bootstrap;
- [ ] concurrent profile bootstrap;
- [ ] normal and administrator authorization;
- [ ] watchlist ownership isolation;
- [ ] token and secret log redaction.

Use generated test keys or mocked JWKS responses.
Do not depend on live Cognito for unit tests.

### 6.2 Frontend tests

Add focused tests for:

- [ ] signup success and failure mapping;
- [ ] confirmation and resend behavior;
- [ ] unconfirmed login recovery;
- [ ] forgotten-password and password-reset behavior;
- [ ] access-token attachment;
- [ ] one refresh retry only;
- [ ] session restoration after refresh;
- [ ] logout and navigation state;
- [ ] missing Cognito build configuration.

### 6.3 Infrastructure tests

Run and retain:

- [x] `sam validate --lint --template-file infra/template.yaml`;
- [x] `cfn-lint` for all infrastructure templates;
- [x] a check proving `GenerateSecret` is false;
- [x] a check proving user-pool retention controls exist;
- [ ] a route comparison between FastAPI protection and API Gateway authorization;
- [ ] a static frontend build using real staging outputs;
- [ ] API image smoke tests with Cognito configuration present.

### 6.4 Staging end-to-end tests

Use new test addresses and record no credentials.

- [ ] Register a valid account.
- [ ] Reject a weak password.
- [ ] Reject a duplicate account without leaking extra details.
- [ ] Confirm the email code.
- [ ] Resend a confirmation code.
- [ ] Login with the confirmed account.
- [ ] Reject a wrong password.
- [ ] Complete one forgotten-password reset.
- [ ] Restore a session after page refresh.
- [ ] Read and update only the user's own watchlist.
- [ ] Reject a normal user from administrator endpoints.
- [ ] Allow the approved administrator to start one bounded scrape.
- [ ] Refresh an expired access token.
- [ ] Logout and reject the old session.
- [ ] Confirm one Cognito user maps to one Supabase investor.

Release gate:

- [ ] Backend tests pass.
- [ ] Frontend tests and static export pass.
- [ ] Infrastructure validation passes.
- [ ] Security review passes.
- [ ] The test reviewer approves staging evidence.
- [ ] Person 1 approves the CloudFormation change set.
- [ ] Person 2 confirms the Supabase migration and executes the change set.

## Phase 7: Staged cutover

Owner: Release owner

Use this order:

1. Back up Supabase.
2. Apply the additive Cognito identity migration.
3. Deploy retained Cognito resources with the backend still in legacy mode.
4. Verify user pool settings and app client settings in AWS.
5. Deploy the backend Cognito code in legacy mode.
6. Run legacy regression tests.
7. Prepare immutable legacy and Cognito frontend candidates from the same SHA.
8. Set the backend to dual mode in a reviewed change set.
9. Publish the prepared Cognito frontend candidate.
10. Run the complete staging end-to-end test set, including administrator TOTP.
11. Set the backend to Cognito mode in a reviewed change set.
12. Promote the verified administrator profile in Supabase.
13. Start the rollback window.

Record these items under one release SHA:

- [ ] Cognito user pool ID and app client ID, without secrets;
- [ ] CloudFormation change-set JSON;
- [ ] migration revision and table checks;
- [ ] backend image digest;
- [ ] frontend artifact checksum;
- [ ] end-to-end results;
- [ ] CloudWatch authentication error summary;
- [ ] rollback decision and deadline.

Do not enable the weekly schedule as part of this authentication release.

## Phase 8: Remove the legacy authentication system

Owner: Backend owner and Person 2

Start only after the rollback window closes.

### 8.1 Remove legacy code

- [ ] Delete legacy signup, login, and database-session code.
- [ ] Delete `backend/app/models/auth_session.py`.
- [ ] Remove its import from `backend/app/models/__init__.py`.
- [ ] Remove password and session helpers from `backend/app/core/security.py`.
- [ ] Remove legacy CRUD password functions.
- [ ] Remove `passlib` and `bcrypt` when no other code uses them.
- [ ] Remove old cookie settings from backend configuration.
- [ ] Remove old cookie and password tests.
- [ ] Remove the legacy provider flag after one stable release.

### 8.2 Apply the contract migration

Create a second Alembic migration.

- [ ] Require `investors.cognito_sub` for active accounts.
- [ ] Drop `investors.hashed_password`.
- [ ] Drop `auth_sessions`.
- [ ] Update the exact database table tests.
- [ ] Keep historical Alembic files unchanged.

Do not use an automatic downgrade in staging or production.
A failed contract migration requires a forward fix.

Exit gate:

- [ ] No application code reads or writes password hashes.
- [ ] No application code reads or writes `auth_sessions`.
- [ ] Every active investor has one unique Cognito subject.
- [ ] All protected routes use Cognito authentication.
- [ ] The full regression set passes after cleanup.

## Rollback plan

### Before the contract migration

Rollback remains possible during the approved window.

1. Stop frontend publication and account testing.
2. Set `AUTH_PROVIDER=dual` through a reviewed change set.
3. Restore the mode-specific legacy frontend release artifact.
4. Verify legacy login, watchlists, and administrator checks.
5. Set `AUTH_PROVIDER=legacy` through a reviewed change set.
6. Keep the additive `cognito_sub` column.
7. Keep the retained Cognito user pool for investigation.
8. Record which Cognito users were created during the failed release.

Do not delete Cognito users automatically.
Do not remove linked investor rows without a reviewed data decision.

### After the contract migration

Legacy rollback is no longer safe because passwords and sessions are gone.
Use a forward fix to repair Cognito authentication.
Restore application images only when their schema requirements still match.

## Security review checklist

- [ ] The browser app client has no secret.
- [ ] Access tokens, not ID tokens, authorize APIs.
- [ ] JWT signature, issuer, expiry, client ID, and token type are verified.
- [ ] Signing-key rotation is handled.
- [ ] Tokens never appear in URLs or logs.
- [ ] CloudFront security headers and the content security policy allow only required origins.
- [ ] Database and SSM secrets stay server-side.
- [ ] Normal users cannot submit or change `role` or `cognito_sub`.
- [ ] Database ownership checks remain on every watchlist mutation.
- [ ] Administrator checks remain on every cost-bearing endpoint.
- [ ] Cognito administrators cannot use administrator routes without TOTP.
- [ ] Cognito resources have retention and deletion protection.
- [ ] Email responses do not expose unnecessary account existence details.
- [ ] Rate-limit and abuse behavior is tested.
- [ ] Supabase Data API remains locked down if the browser does not use it.

## Final acceptance criteria

The change is complete only when all statements are true:

- A new user signs up through Cognito, not FastAPI password storage.
- The user confirms their email before login completes.
- One Cognito `sub` maps to one Supabase investor UUID.
- The browser sends Cognito access tokens to protected API routes.
- API Gateway checks mapped protected routes.
- FastAPI validates every protected request independently.
- Existing record ownership and administrator rules still hold.
- Supabase stores no new password or session data.
- Legacy password and session storage is removed after the rollback window.
- Tests cover signup, confirmation, login, password reset, refresh, logout, ownership, and administrator access.
- Release and rollback evidence is tied to one full Git SHA.

## Reference documentation

- AWS Cognito SignUp API: https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_SignUp.html
- AWS Cognito ConfirmSignUp API: https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_ConfirmSignUp.html
- AWS Cognito app clients: https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html
- API Gateway HTTP API JWT authorizers: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html
- Supabase AWS Cognito integration: https://supabase.com/docs/guides/auth/third-party/aws-cognito
- Supabase PostgreSQL connections: https://supabase.com/docs/guides/database/connecting-to-postgres
