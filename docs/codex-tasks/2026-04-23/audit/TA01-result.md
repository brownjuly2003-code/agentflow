# TA01 result

## Quick fix status

- Task context was written against `b8ba5f7`, but current `origin/main` is `a010a2d` as of 2026-04-23.
- The requested quick fix is already present on `main` in commit `bbde79c` (`ci(test-integration): install cloud extras for pyiceberg-using src modules`).
- Evidence: diff `b8ba5f7..a010a2d` in `.github/workflows/ci.yml` changes `test-integration` install from `pip install -e ".[dev]"` to `pip install -e ".[dev,cloud]"`.
- Acceptance evidence for the regression itself: CI run `24817461782` on `a010a2d` collected 185 integration tests and failed later on one real test, not on `ModuleNotFoundError: pyiceberg` during collection.
- No additional commit/push was created in this execution, because repeating an already-landed one-line fix would produce a no-op duplicate commit.

## CI workflow matrix (HEAD a010a2d)

| Workflow | Last run | Conclusion | Internal jobs status | Root cause | Action |
|----------|----------|------------|----------------------|------------|--------|
| Nightly Backup | `24817375807` (`2026-04-23T04:49:43Z`) | `success` | `backup:success` | `-` | `-` |
| Chaos Engineering | `24705766087` (`2026-04-21T05:29:42Z`) | `failure` | `chaos-smoke:skipped chaos-full:failure` | Last red run was on pre-fix SHA `2e4b2e8`: `tests/chaos/conftest.py` import chain failed with `ModuleNotFoundError: pyiceberg`. Current `main` already installs `.[dev,cloud]` in `chaos.yml`. | `acceptable until 2026-04-24 04:00 UTC scheduled run validates the post-fix workflow on main` |
| CI | `24817461782` (`2026-04-23T04:52:39Z`) | `failure` | `lint:success schema-check:success test-unit:failure test-integration:failure perf-check:skipped terraform-validate:success record-deployment:skipped` | `test-unit`: 375 tests passed, but coverage gate failed at `62.27% < 80%`. `test-integration`: `tests/integration/test_iceberg_sink.py::test_repo_default_config_writes_to_rest_catalog` failed because `_wait_for_catalog` hit `[Errno 13] Permission denied: '/warehouse'`. | `new ticket: T10-ci-post-quickfix-red-jobs in 2026-04-24/` |
| Contract Tests | `24815235708` (`2026-04-23T03:33:29Z`) | `success` | `contract:success` | `-` | `-` |
| DORA Metrics | `24814675744` (`2026-04-23T03:13:01Z`) | `success` | `dora-report:success` | `-` | `-` |
| E2E Tests | `24817461794` (`2026-04-23T04:52:39Z`) | `failure` | `e2e:failure` | Inferred from the run log plus `.github/workflows/e2e.yml`: all four services were healthy by `2026-04-23T04:54:11Z`, but the startup loop still timed out after 180s. The inline parser expects a single JSON payload from `docker compose ... ps --format json` and never recognizes the healthy service set. | `new ticket: T11-e2e-compose-health-detection in 2026-04-24/` |
| Load Test | `24817461775` (`2026-04-23T04:52:39Z`) | `failure` | `load-test:failure` | Real performance gate failure: p95 exceeded thresholds for `/v1/entity/order/{id}` (1600 ms > 50 ms), `/v1/entity/user/{id}` (1700 ms > 50 ms), `/v1/entity/product/{id}` (1500 ms > 50 ms), `/v1/metrics/{name}` (1700 ms > 100 ms), `/v1/query` (1500 ms > 500 ms), `/v1/batch` (1500 ms > 200 ms), `/v1/health` (53000 ms > 20 ms). | `existing ticket T06-performance-workflows-baseline-repair` |
| Mutation Testing | `workflow_dispatch/schedule only; never run on main since 2026-04-20` | `never_run` | `-` | No run history on `main` after workflow creation. | `existing ticket T07-mutation-workflow-first-green-run` |
| Performance Regression | `pull_request only; never run on main since 2026-04-20` | `never_run` | `-` | PR-only workflow; no run on `main` by design. | `existing ticket T06-performance-workflows-baseline-repair` |
| Nightly Performance | `24761959139` (`2026-04-22T05:31:06Z`) | `failure` | `performance-regression:failure` | Last red run was on pre-fix SHA `2e4b2e8`: `scripts/run_benchmark.py` failed while seeding demo data because `src/processing/local_pipeline.py:22` raised `ModuleNotFoundError: pyiceberg`. Current `main` already installs `.[dev,load,cloud]` in `performance.yml`, but no post-fix green proof exists yet. | `existing ticket T06-performance-workflows-baseline-repair` |
| Publish TypeScript SDK | `tag-only; never run on main since 2026-04-20` | `never_run` | `-` | Trigger requires `sdk-v*` tags; repository currently has no matching release proof on `main`. | `existing ticket T08-sdk-publish-workflows-release-proof` |
| Publish Python SDK | `tag-only; never run on main since 2026-04-20` | `never_run` | `-` | Trigger requires `sdk-v*` tags; repository currently has no matching release proof on `main`. | `existing ticket T08-sdk-publish-workflows-release-proof` |
| Security Scan | `24817461780` (`2026-04-23T04:52:39Z`) | `success` | `bandit:success safety:success trivy:success` | `-` | `-` |
| Staging Deploy | `24817461777` (`2026-04-23T04:52:39Z`) | `failure` | `staging:failure` | Staging deploy reached the E2E phase and passed 15/16 selected tests, but `tests/e2e/test_smoke.py::test_webhook_test_endpoint_delivers_callback` failed because the callback queue stayed empty for 5 seconds. | `new ticket: T12-staging-webhook-callback-reliability in 2026-04-24/` |
| Terraform Apply | `workflow_dispatch only; never run on main since 2026-04-20` | `never_run` | `-` | Manual apply workflow has no safe proof run on `main` yet. | `existing ticket T09-terraform-apply-oidc-readiness` |

## New tickets created

- `docs/codex-tasks/2026-04-24/T10-ci-post-quickfix-red-jobs.md`
- `docs/codex-tasks/2026-04-24/T11-e2e-compose-health-detection.md`
- `docs/codex-tasks/2026-04-24/T12-staging-webhook-callback-reliability.md`
