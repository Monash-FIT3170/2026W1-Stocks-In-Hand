# Remove the deployment-test deploy roles

Status: accepted, 2026-10-14

`infra/github-oidc.yaml` held a second pair of deploy roles for an isolated
deployment-test workflow: `GitHubDeploymentTestRole`
(`stocks-in-hand-github-deployment-test`) and
`DeploymentTestCloudFormationExecutionRole`
(`stocks-in-hand-cloudformation-deployment-test-execution`). The team decided
the deployment-test stack is not needed, so both roles and their two outputs
are removed. Nothing on `main` uses them, and the workflow they were made for
cannot run against `main`. One pair of deploy roles is left, for staging, and
`backend/tests/test_github_oidc.py` checks it against what each staging
workflow needs.

## Evidence

- No workflow on `main` signs in as the test role. All six AWS workflows
  assume `vars.AWS_DEPLOY_ROLE_ARN`, the staging role.
- The only workflow that used the test roles, `deployment-test.yml`, exists
  only on the `origin/deployment-test` branch, which was never merged. Its
  last commit is `5cdcb86` (2026-08-17). The branch keeps that workflow as
  history.
- That workflow could not run against `main`:
  - it names its stacks `stocks-in-hand-depl-test-<run id>`, but `main`'s test
    role may only change stacks named `stocks-in-hand-deployment-test-*`;
  - it maps 5 of the template's 7 image functions, and SAM refuses a deploy
    that does not map them all;
  - it passes `Environment=depl-test-...`, which `infra/template.yaml` refuses,
    because its only allowed value is `staging`;
  - it pushes to `stocks-in-hand-deployment-test-*` ECR repositories, which
    only the branch's unmerged copy of `infra/bootstrap.yaml` creates.
- `main`'s copy of the roles is the one from `5fb9d54` on that branch.
  `d04b23b` ("Preserve deployment test OIDC roles") copied it to `main`,
  `b7ed1d6` reverted that and `167a23b` restored it, all within 27 minutes on
  2026-08-31. It lacks the branch's five later changes to the roles (`b52d24f`,
  which renamed the stacks, `a5a4a33`, `e642533`, `537bc24` and `5cdcb86`).

## Considered options

- Keep both pairs, bring `main`'s copy up to date with the branch, and pin how
  the test roles may differ from the staging ones with a test. The workflow
  would still need the branch's template and bootstrap changes before it could
  deploy.
- Define the role pair once. A nested stack needs an S3 bucket and
  `aws cloudformation package` for a stack that is deployed by hand. A second
  stack from one parameterised template needs the role names as parameters,
  the account's one OIDC provider passed in, and `Fn::If` for every statement
  that differs: 9 statements and the ECR grant between the GitHub roles, and
  2 statements between the execution roles. `Fn::ForEach` cannot give each
  role its own statements, and it would rename a role that has a fixed name.

## Consequences

- The OIDC stack is deployed by hand (`infra/README.md` §10). Review its next
  change set before executing it: it may remove only the two roles above and
  the `GitHubDeploymentTestRoleArn` and
  `DeploymentTestCloudFormationExecutionRoleArn` outputs. `GitHubOidcProvider`,
  `GitHubDeploymentRole` and `CloudFormationExecutionRole` must not change.
- `vars.AWS_DEPLOY_TEST_ROLE_ARN` stops working. Delete it from GitHub if it is
  set.
- Anything a deployment-test run left in the account, such as
  `stocks-in-hand-depl-test-*` stacks, `/stocks-in-hand/deployment-test/*` SSM
  parameters or `stocks-in-hand-deployment-test-*` ECR repositories, is not
  part of the OIDC stack and has to be removed by hand.
- Bringing the deployment-test stack back means rebuilding its roles from
  `origin/deployment-test` and updating that workflow to work with `main`.
