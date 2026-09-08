# Codecov setup

`codecov.yml` in the repository root is retained policy, not a live pipeline.
No workflow uploads coverage to Codecov, no README badge points at it, and the
blocking coverage gates are repository-owned. This page says what the tracked
config is for today and what reintroducing external reporting would take.

**Audience:** repository maintainer deciding whether to reintroduce external coverage reporting

**Prerequisites:** GitHub access as the repository owner; only a reintroduction additionally needs a Codecov account that can enable the repository

**Upload status:** no workflow uploads coverage to Codecov (audit F-06 removed it).

## Why there is no upload

On 2026-07-30, CI run
[`30575838038`](https://github.com/brownjuly2003-code/agentflow/actions/runs/30575838038)
completed every test and every local coverage gate. The Codecov OIDC token
exchange and the upload queueing also succeeded — and then Codecov returned
`Repository not found` while processing the report, because the repository had
never been enabled in the external service.

Audit F-06 removed the upload step and the README badge rather than keep a step
that could not work. `.github/workflows/ci.yml` records the decision on the
`test-unit` job, which also gave up the `id-token: write` permission it held
only for that upload. [Release readiness](../release-readiness.md) states the
same, and `tests/unit/test_repository_coverage_artifact.py` fails if a Codecov
action reappears in any job.

## What holds the coverage line instead

These run inside CI with no external service involved, and they block:

- a 60% line+branch floor across `src/agentflow_runtime` and `sdk` on the full
  unit and property suites;
- `diff-cover` at 80% on changed code, from
  `.artifacts/coverage/coverage.xml`;
- separate 90% floors for security-critical modules (validators, freshness
  monitor, event producer, SQL guard, rate limiter, auth manager).

Codecov was only ever reporting on top of these.

## Why `codecov.yml` is still tracked

`scripts/validate_project_claims.py` reads it and fails the required `lint` job
when `coverage.status.patch.default.target` disagrees with the changed-code
floor in [`config/project_claims.toml`](../../config/project_claims.toml). The
file is therefore the machine-checked record of the patch-coverage policy, and
it is the configuration a reintroduced upload would consume unchanged. Deleting
it breaks `lint`.

Its policy:

- project coverage must not drop by more than 2 percentage points
  (`project.default.threshold: 2%`);
- new code in a pull request must be at least 80% covered
  (`patch.default.target: 80%`) — the value the claims validator pins;
- `tests/`, `scripts/`, `examples/`, `sdk-ts/`, and `notebooks/` are ignored,
  because they are not the production surface.

Validate the file against the service without uploading anything:

```bash
curl --data-binary @codecov.yml https://codecov.io/validate
```

Expected response: `Valid!`.

## Reintroducing external reporting (not done)

1. Sign in to https://codecov.io with the GitHub account that owns the
   repository and enable the repository. Until this is done, any upload
   repeats the 2026-07-30 `Repository not found` result.
2. Publish the coverage report as an artifact first: the `test-unit` job writes
   `.artifacts/coverage/coverage.xml` but does not upload it, and only
   `coverage-control-plane.xml` from `test-integration` is published today.
3. Add the Codecov step in a **separate** job that consumes that artifact. F-06
   removed it from `test-unit` so that the job executing repository-owned test
   code does not carry a token-exchange capability; putting it back there
   reverses that decision.
4. Grant `id-token: write` on that new job alone for a tokenless OIDC upload
   (`use_oidc: true`). If policy forbids tokenless uploads, store a project
   upload token as the `CODECOV_TOKEN` secret and pass `token:` instead.
5. Keep `fail_ci_if_error: false` so an unreachable service cannot fail a build
   whose blocking gates already passed.
6. Update the **Upload status** line above and the Codecov sentence in
   [PROJECT_CLOSURE.md](../PROJECT_CLOSURE.md).
   `tests/unit/test_codecov_reporting_docs.py` fails while the pages and the
   workflows disagree.
