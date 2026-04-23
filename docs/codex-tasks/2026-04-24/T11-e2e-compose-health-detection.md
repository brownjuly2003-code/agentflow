# T11 - E2E workflow: repair compose health detection and reach pytest

**Priority:** P1 - **Estimate:** 1-2ч

## Goal

Сделать `E2E Tests` green, чтобы workflow reliably доходил до `pytest tests/e2e/`.

## Context

- Latest E2E run on `main`: `24817461794` for SHA `a010a2d`.
- Workflow fails in the `Start E2E stack` step before any pytest execution.
- The log shows all required services (`agentflow-api`, `redis`, `kafka`, `postgres`) healthy by `2026-04-23T04:54:11Z`, but the step still exits at `2026-04-23T04:57:12Z` with `E2E compose services did not become healthy within 180 seconds.`
- The inline Python in `.github/workflows/e2e.yml` parses `docker compose -f docker-compose.e2e.yml ps --format json` via `json.loads(result.stdout or "[]")`; the observed behavior strongly suggests the parser never recognizes the healthy service set.

## Deliverables

1. Reproduce and confirm the exact output format of `docker compose ... ps --format json` in the workflow environment.
2. Replace the brittle health-detection logic with a parser/check that works reliably on GitHub runners.
3. Keep the health gate explicit: the workflow should still wait for the required services, not just sleep longer.
4. Get one green recent run for `E2E Tests`.

## Acceptance

- The `Start E2E stack` step exits because services are actually healthy, not because the timeout was merely extended.
- `pytest tests/e2e/` executes in the workflow.
- A recent run of `E2E Tests` on `main` or `workflow_dispatch` is green.

## Notes

- Do not treat a raw timeout bump as a sufficient fix unless the root cause is proven to be genuine slow startup.
