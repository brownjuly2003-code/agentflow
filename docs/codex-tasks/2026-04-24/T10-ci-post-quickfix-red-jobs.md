# T10 - CI: close remaining red jobs after the pyiceberg quick fix

**Priority:** P0 - **Estimate:** 2-4ч

## Goal

Сделать `CI` green после уже влитого quick fix `bbde79c`, не размывая signal workflow.

## Context

- Latest CI run on `main`: `24817461782` for SHA `a010a2d`.
- `lint`, `schema-check`, `terraform-validate` green.
- `test-unit` ran successfully at the test level (`375 passed`), but the workflow failed on the coverage gate: `62.27% < 80%`.
- `test-integration` no longer fails on `ModuleNotFoundError: pyiceberg` during collection; it now runs 185 tests and fails only on `tests/integration/test_iceberg_sink.py::test_repo_default_config_writes_to_rest_catalog`.
- The failing integration test times out in `_wait_for_catalog` because the catalog path resolves to `/warehouse` and the runner gets `[Errno 13] Permission denied: '/warehouse'`.

## Deliverables

1. Decide and document the intended CI coverage contract for `test-unit`:
   - keep `80%` and add the missing tests,
   - or narrow the measured scope,
   - or adjust the threshold with explicit rationale.
2. Fix the repo-default REST catalog path/permissions so the integration test can create and use a writable warehouse on GitHub runners.
3. Get one green `CI` run where `perf-check` is allowed to execute.

## Acceptance

- `test-unit` is green with an intentional coverage contract, not by hiding test files or silently dropping measurement scope.
- `test-integration` is green and `test_repo_default_config_writes_to_rest_catalog` passes on CI.
- `CI` workflow reaches a non-skipped `perf-check` on a recent run.

## Notes

- Do not reopen the already-fixed `pyiceberg` collection regression.
- Do not skip or xfail the failing integration test as the primary remedy.
