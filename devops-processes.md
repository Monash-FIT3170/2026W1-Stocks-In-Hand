# DevOps Deployment Process: Current Two-Person Manual Flow vs. Gated GitOps Automation

## A note on scope before comparing approaches

Everything in `infra/`, `deployment.md`, and the five existing workflows targets a single
**staging** deployment (`stocks-in-hand-staging`) — `deployment.md:9-11` is explicit that this
is "deliberately a small deployment" and does *not* create a second production stack. There is
currently no `infra/template.yaml` parameter set, no OIDC role, and no CloudFormation stack for
a `production` environment. Before implementing GitOps *to production*, that gap needs an
explicit decision: are you promoting the existing staging stack to be treated as production, or
adding a genuinely separate production stack/account that staging promotes into? The
implementation guide below assumes the latter (a proper staging → production promotion
pipeline), since it's the safer and more standard GitOps pattern, but calls out what changes if
you choose the former.

---

## 1. Current approach: manual two-person change-set review

Recap of what's actually implemented today (`.github/workflows/deploy-staging.yml`,
`execute-staging-change-set.yml`, `publish-staging-frontend.yml`,
`prepare-staging-backend-rollback.yml`, `rollback-staging-frontend.yml`):

- All five workflows trigger **only** on `workflow_dispatch` — nothing deploys automatically on
  push or merge.
- "Prepare staging release" is run manually by a developer. It builds and pushes the three
  Lambda images (tagged with the full git SHA), then creates a CloudFormation change set with
  `sam deploy --no-execute-changeset` and uploads the change-set JSON as a build artifact. It
  does **not** deploy anything.
- **Person 1** downloads that artifact and reads the literal infrastructure diff (which
  resources are being added/changed/replaced, IAM policy changes, etc.) before approving.
- **Person 2** manually runs "Execute approved staging change set," supplying the specific
  change-set ARN Person 1 reviewed — not a freshly re-derived one — so the thing that gets
  executed is exactly the thing that was reviewed.
- The GitHub `staging` environment additionally requires reviewer approval before either
  workflow's job can run (this is a second, independent gate on top of the Person 1/Person 2
  process).
- Frontend publishing and rollback are separate, similarly manual and gated workflows.
- Database migrations are entirely outside CI — run by a human, once, from a local machine,
  against a distinct migration-mode database URL (`infra/README.md:118-150`).

---

## 2. Proposed approach: automatic trigger, mandatory review gate

What you're describing is standard **GitOps with an approval gate**: a deployment pipeline that
runs automatically off a git event (merge to a branch, or a tag/release), rather than a human
manually invoking each stage — but with a required-reviewers checkpoint that pauses the
pipeline before anything touches production, so no deployment reaches production without a
human clicking "approve" first.

Concretely, this uses GitHub Environments' built-in **required reviewers** protection rule: a
job that declares `environment: production` pauses and waits for one or more designated people
to approve the run in the GitHub UI before the job's steps execute. This is a real, supported
GitHub feature (not something you'd have to build) and is already partially in use today via
the `staging` environment — the difference is *what triggers the run* and *how many separate
manual invocations are required to get from commit to deployed*.

---

## 3. Pros and cons

| | Current (manual, two-workflow) | Proposed (auto-trigger, gated) |
|---|---|---|
| **Trigger** | Developer must remember to run "Prepare staging release," then a second person must remember to run "Execute" | Deployment is queued automatically the moment code lands on the target branch/tag — nothing to remember or forget |
| **What's reviewed** | Person 1 reads the literal CloudFormation change-set diff, line by line, before anything is approved | Reviewer approves inside the GitHub UI; whether they see the actual infra diff depends on whether it's surfaced in the run (see §5.2 — this is achievable but isn't automatic) |
| **Review-to-execute gap** | Change-set ARN is explicit and pinned — Person 2 cannot accidentally execute a *different* change set than the one reviewed | If reviewers approve the same job that executes, this property is preserved automatically; if approval and execution are split across separate triggers, you must re-derive the same discipline |
| **Speed / friction** | Two manual `workflow_dispatch` invocations plus coordination between two specific people — slow, easy to stall on availability | One approval click after an automatic trigger — meaningfully faster, less coordination overhead |
| **Human error surface** | Two people can each forget a step, use the wrong SHA, or run workflows out of order | Fewer manual steps means fewer chances to fat-finger an input (e.g. the `release_sha` regex-validated inputs in the rollback workflows exist specifically to guard against manual typos) |
| **Auditability** | Every action is an explicit, named `workflow_dispatch` run with inputs in the Actions log | Still fully auditable (GitHub records who approved what and when), but the trigger itself is an implicit "someone merged to main," which is a less deliberate act than "someone chose to deploy right now" |
| **Blast radius of a bad merge** | A bad merge just sits in the branch; nothing happens until a human deliberately starts a deployment | A bad merge automatically queues a production deployment attempt — you are now relying entirely on branch protection (required PR review, required checks) *before* the merge, plus the environment gate *after* it, as your only safety nets |
| **Database migrations** | Explicitly kept out of automation entirely, run manually with a distinct connection string, specifically because `infra/README.md` treats schema changes as higher-risk than infra/code changes | Needs a deliberate decision — see §5.4. Auto-including migrations in a fully automated pipeline is the single riskiest part of this proposal |
| **Rollback** | Manual, reviewed, symmetric to forward deployment | Can stay manual (recommended) or follow the same auto+gate pattern — see §5.5 |
| **Team buy-in / psychological safety** | Slower, but every deployment has a named human who explicitly typed "yes, deploy this" for that specific change — this is likely the actual thing your team wants preserved, not literally the two-workflow mechanism | Can preserve the same guarantee (a named human approves before production is touched) if the gate is designed correctly — the disagreement may be resolvable by making sure the approval step is *substantively* equivalent to today's review, not just a rubber stamp |

**The honest tradeoff:** the current process is slow because review and execution are two
separate manual acts by two separate people, coordinated by hand. That's real friction, and
automating the *trigger* removes it without necessarily removing the *review*. The risk in your
proposal isn't "automation" per se — it's whether the mandatory review step actually shows
reviewers the same infrastructure-level diff Person 1 reviews today, or whether it degrades into
a generic "click approve" button that people rubber-stamp because they can't easily see what
they're approving. Get that part right (§5.2) and most of your team's likely objection goes
away, because the actual safety property — *a human reviews the real change before it reaches
production* — is preserved; only the manual coordination overhead is removed.

---

## 4. Recommended compromise design

1. **Split staging and production.** Let staging auto-deploy on every merge to `main` with a
   light or no approval gate (fast feedback for developers, low blast radius since it's already
   budget-capped and non-customer-facing). Only gate the promotion **from staging to
   production** — triggered by a git tag or GitHub Release — with mandatory reviewer approval.
   This is the standard "build once, promote through environments" GitOps pattern, and it
   directly answers your team's concern (nothing reaches production without human sign-off)
   while giving you the "no manual effort" property for the environment where it matters least.
2. **Keep the change-set-then-execute split, but automate the trigger and put the gate between
   them**, not around two separate manually-invoked workflows. One pipeline run should carry the
   change-set ARN from the "create" job to the "execute" job automatically (as a job output),
   so a human never has to manually copy an ARN between two separate workflow invocations — the
   pinning property (execute exactly what was reviewed) is preserved by the pipeline, not by a
   person.
3. **Make the diff visible at the approval point.** Have the "create change set" job write the
   changed resources to the GitHub Actions job summary (`$GITHUB_STEP_SUMMARY`) before the
   `production` environment gate. Reviewers approving a pending deployment in GitHub's UI can
   open the run and read that summary before clicking approve — so the review step stays
   substantively the same as today's manual JSON inspection, it just happens in-run instead of
   via a downloaded artifact.
4. **Require at least two reviewers on the `production` environment**, and use GitHub's
   deployment branch/tag policy to restrict which refs are even eligible to deploy to it (e.g.
   only tags matching `v*`). This reconstructs your current "two different people" guarantee
   without requiring two separate manual workflow runs.
5. **Keep database migrations and rollback as their own explicitly-gated, non-automatic steps**
   regardless of how much of the rest of the pipeline you automate (§5.4, §5.5) — these are the
   two places where "automatic" and "irreversible" overlap most dangerously.

---

## 5. Implementation guide

### 5.1 Add a `production` GitHub environment with required reviewers

In the repo's **Settings → Environments**, create a `production` environment (distinct from
`staging`):
- Enable **Required reviewers**, add the specific people/team who must approve (2+
  recommended). GitHub will not let the person who triggered the run approve their own
  deployment if they're the only required reviewer and self-review protections are enabled for
  the org — but don't rely on that alone; requiring 2 named reviewers is the robust guarantee.
- Set a **deployment branch/tag policy** restricting `production` to protected refs only (e.g.
  `refs/tags/v*`, or `main` if you go with a merge-triggered model instead of tags).
- Optionally add a **wait timer** if you want a mandatory cooling-off period even after
  approval.

This is the mechanism that gives you "GitHub Actions is capable of deploying without manual
effort, but a review step mandates certain people approve before it completes" — it's a native
feature, not something you need to build.

### 5.2 Restructure the workflow into build → gated-deploy stages in one pipeline

Today, "create change set" and "execute change set" are two separate workflows, each separately
`workflow_dispatch`-triggered, coordinated by a human copying the change-set ARN between them.
Collapse this into **one workflow with sequential jobs**, since GitHub environment protection
rules apply per-job, not per-step — you can't gate half of a job:

```yaml
on:
  push:
    tags:
      - "v*"          # or: push to main, if you prefer merge-triggered

jobs:
  build-and-plan:
    runs-on: ubuntu-latest
    permissions: { contents: read, id-token: write }
    outputs:
      change_set_arn: ${{ steps.create.outputs.arn }}
      release_sha: ${{ steps.sha.outputs.sha }}
    steps:
      # ... build/push the three images (unchanged from deploy-staging.yml) ...
      # ... sam deploy --no-execute-changeset (unchanged) ...
      - name: Post change-set summary
        run: |
          aws cloudformation describe-change-set --change-set-name "$ARN" \
            --query 'Changes[].ResourceChange.{Action:Action,Resource:LogicalResourceId,Type:ResourceType}' \
            --output table >> "$GITHUB_STEP_SUMMARY"

  deploy:
    needs: build-and-plan
    environment: production          # <-- the mandatory human gate lives here
    runs-on: ubuntu-latest
    permissions: { contents: read, id-token: write }
    steps:
      - name: Execute approved change set
        run: aws cloudformation execute-change-set --change-set-name "${{ needs.build-and-plan.outputs.change_set_arn }}"

  publish-frontend:
    needs: deploy
    environment: production          # reuse the same gate, or a lighter one if you want frontend to ship faster than backend
    runs-on: ubuntu-latest
    steps:
      # ... unchanged from publish-staging-frontend.yml, but using needs.build-and-plan.outputs.release_sha ...
```

The reviewer clicking "approve" on the `deploy` job is now shown the run, including
`build-and-plan`'s job summary containing the actual resource diff — reconstructing today's
"Person 1 reads the change-set JSON" step without a separate manual workflow invocation.

### 5.3 IAM/OIDC changes

`infra/github-oidc.yaml`'s trust policy currently scopes the deployment role to
`repo:<org>/<repo>:environment:staging`. For production you need either:
- A **second, separate stack deployment** of `github-oidc.yaml` with
  `GitHubEnvironment=production`, producing a distinct `GitHubDeploymentRole` scoped to
  `repo:<org>/<repo>:environment:production` — recommended if production is a genuinely separate
  AWS account/stack, since it keeps the IAM blast radius identical to the account boundary.
- If staying within the same AWS account, at minimum change the environment name referenced in
  the trust condition and in the workflow's `environment:` key so the OIDC subject claim
  actually matches; the current template's `GitHubEnvironment` parameter already supports this
  without code changes, just a separate `aws cloudformation deploy` with a different parameter
  value and stack name.
- Remember to also fix the missing `ecr:DescribeImages` permission (flagged separately in
  `recommendations.md` §1.1) in whichever role serves the new pipeline — this bug will surface
  identically in an automated flow.

### 5.4 Database migrations — keep this out of full automation

This is the part of your proposal to be most conservative about. `deployment.md` and
`infra/README.md` treat migrations as categorically different from code/infra deploys:
run manually, using a *different* database connection (session/direct pooler, not the
transaction pooler Lambdas use), with an explicit pre-migration backup and duplicate-row
preview query, and with an explicit statement that "database migrations are never downgraded
automatically."

Recommendation: even in a fully GitOps'd deploy pipeline, keep migrations as a **separate,
explicitly-triggered job** gated by its own environment approval (it can still be
`workflow_dispatch`-only, or gated behind a distinct `production-migrations` environment with
its own required reviewers), run *before* the image/infra deploy job, not folded into the same
automatic trigger. Irreversible schema changes are the one category of change where "a human
deliberately chose to do this right now" is worth keeping, even if everything else becomes
push-button.

### 5.5 Rollback — recommend leaving these manual

`prepare-staging-backend-rollback.yml` and `rollback-staging-frontend.yml` are inherently
incident-response tooling, not steady-state pipeline stages. There's little value in
auto-triggering a rollback off a git event (what event would that even be?), and real value in
keeping them as deliberately-invoked, reviewed `workflow_dispatch` actions exactly as they are
today — just point them at the new `production` environment/role once that exists. (Separately,
recall §2.5 of `recommendations.md`: fix the rollback workflow's hardcoded feature-flag
parameters before relying on it more heavily.)

### 5.6 Staging → production promotion flow

Putting it together end to end:

1. PR merges to `main` → **staging** deploy pipeline runs automatically, no gate (or a light one
   — e.g. a single non-blocking reviewer), since staging is cheap and low-risk by design.
2. Once staging is validated (manually, or via smoke tests you add to the pipeline), someone
   cuts a tag/release (e.g. `v1.4.0`).
3. The tag push triggers the **production** pipeline: build-and-plan → `production`
   environment gate (required reviewers see the change-set summary) → deploy → publish frontend.
4. Migrations, if any are pending for that release, are applied via the separate gated migration
   job (§5.4) before step 3's deploy job runs.
5. Rollback stays a manual, separately-invoked, reviewed action (§5.5).

---

## 6. What specifically changes vs. the current strategy

| Aspect | Current | After this change |
|---|---|---|
| Trigger | Manual `workflow_dispatch`, run by a developer when ready | Automatic on tag push (or merge to `main` for staging) |
| Number of manual actions from commit to deployed | 2 workflow runs (prepare, then execute) + coordination between 2 people | 1 approval click, after an automatic trigger |
| Review artifact | Downloaded `change-set.json` inspected locally | Change-set resource diff posted to the job's `$GITHUB_STEP_SUMMARY`, visible in the same run a reviewer approves |
| Change-set → execute pinning | Enforced by a human copying the exact ARN between two workflow invocations | Enforced by the pipeline passing the ARN as a job output — no manual copy step, same pinning guarantee |
| Approval mechanism | GitHub environment required-reviewers gate, layered on top of the separate Person 1/Person 2 process | GitHub environment required-reviewers gate *is* the review mechanism — one job, gated |
| Environments | Only `staging` exists | `staging` (auto, light gate) + `production` (tag-triggered, mandatory 2-reviewer gate) as separate stacks/roles |
| IAM/OIDC | One role, trust-scoped to `environment:staging` | Second role added, trust-scoped to `environment:production`, plus the `ecr:DescribeImages` fix |
| Database migrations | Fully manual, outside CI | Still a separate, explicitly-gated job — deliberately *not* folded into the automatic trigger |
| Rollback | Manual, reviewed `workflow_dispatch` | Unchanged — still manual and reviewed |
| Number of workflow files | 5 (prepare, execute, rollback-prepare, publish-frontend, rollback-frontend) | Fewer, larger workflows: one combined staging pipeline, one combined production pipeline (build+plan+gate+deploy+publish), migration and rollback workflows kept separate |
