# Codecov setup

This guide connects the AgentFlow repository to Codecov so the coverage
badge in `README.md` resolves and coverage reports flow in on every CI
run.

## How uploads work today

- `ci.yml` calls pinned `codecov/codecov-action` v7.0.0 with
  `use_oidc: true` during the `test-unit` job.
- OIDC uploads do not require a long-lived `CODECOV_TOKEN`; the action
  exchanges the GitHub OIDC token for a short-lived Codecov credential.
- `fail_ci_if_error: false` keeps CI green even if Codecov is temporarily
  unreachable or the repository has not yet been enabled there.
- Coverage still fails closed inside CI: the full suite enforces a 60%
  line/branch floor, `diff-cover` enforces 80% on changed code, and
  security-critical modules have separate 90% gates.

## Current external status

On 2026-07-30, CI run
[`30575838038`](https://github.com/brownjuly2003-code/agentflow/actions/runs/30575838038)
completed every test and local coverage gate successfully. Codecov OIDC token
exchange and upload queueing also succeeded, but Codecov returned
`Repository not found` while processing the report. This is an external
repository-activation gap, not a test or coverage failure. Complete the
one-time setup below before treating the Codecov dashboard or badge as current.

## One-time setup

1. Sign in to https://codecov.io with the GitHub account that owns the
   repository.
2. Open the organization page and enable the repository.
3. In the repository settings on Codecov, confirm tokenless uploads are
   allowed (Settings -> General -> "Allow tokenless uploads from GitHub
   Actions" or the equivalent OIDC toggle).
4. Nothing to add in GitHub secrets — the OIDC upload path does not need
   a `CODECOV_TOKEN`.

Optional: if tokenless uploads are disabled by policy, create a project
upload token and store it as the `CODECOV_TOKEN` repository secret, then
drop `use_oidc: true` and add `token: ${{ secrets.CODECOV_TOKEN }}` to
the workflow step.

## Validate the config

```bash
curl --data-binary @codecov.yml https://codecov.io/validate
```

Expected response: `Valid!`.

## Verify the pipeline

1. Push a commit to `main` or open a pull request.
2. After the repository is enabled in Codecov, confirm the `Upload coverage`
   step reports a successful external upload.
3. Open the Codecov dashboard and confirm a new report appears for the
   commit SHA.
4. Reload `README.md` on GitHub — the `codecov` badge should resolve to
   the current coverage number (usually within a minute of the upload).

## Policy summary

`codecov.yml` in the repository root enforces:

- Project coverage must not drop by more than 2 percentage points
  (`project.default.threshold: 2%`).
- New code in a pull request must be at least 80% covered
  (`patch.default.target: 80%`).
- Coverage for `tests/`, `scripts/`, `examples/`, `sdk-ts/`, and
  `notebooks/` is ignored because those directories are not part of the
  production surface.

These Codecov policies are additional reporting/status checks once the
external repository is enabled. The blocking repository-owned coverage floors
remain the `pytest-cov`, `diff-cover`, and module-specific commands in
`.github/workflows/ci.yml`.
