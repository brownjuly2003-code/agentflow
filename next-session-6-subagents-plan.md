# Next Session Six-Subagent Plan

Status: completed on 2026-05-02.

## Goal

Close the remaining low-risk follow-ups found during the five-agent audit without mixing ownership or weakening release gates.

## Subagents

- [x] Agent 1, test environment: fix `schemathesis` pytest plugin dependency, stabilize `anyio_backend`, and document/automate a writable pytest basetemp. Verify: `python -m pytest --collect-only -q tests/unit tests/property` exits 0 without plugin import errors.
- [x] Agent 2, compose and CI: fix `docker-compose.prod.yml` ClickHouse env interpolation for default DuckDB mode, review Kafka advertised listeners, and add PR coverage for E2E paths if still missing. Verify: relevant `docker compose ... config --quiet` commands exit 0 and workflow syntax validates.
- [x] Agent 3, TypeScript SDK typing: replace the constructor inline options type with `ClientOptions`, remove the resilience cast, and add a compile-time usage check for `retryPolicy`/`circuitBreaker`. Verify: `cd sdk-ts && npm run typecheck && npm run test:unit`.
- [x] Agent 4, lineage and streaming correctness: add entity-type filtering to lineage and decide whether `/v1/stream/events` must filter `events.validated`. Verify: targeted integration tests cover shared IDs and non-validated topics.
- [x] Agent 5, contracts and docs drift: update `contracts/entities/order.yaml` currency wording and refresh stale README/release-readiness test counts only from fresh command output. Verify: contract checks and `rg "743 passed|741 passed"` show no stale contradictions.
- [x] Agent 6, API docs accuracy: clarify that `demo-key` examples require `AGENTFLOW_DEMO_MODE=true`, and align architecture docs with DuckDB-default plus optional ClickHouse serving. Verify: `rg "demo-key|AGENTFLOW_DEMO_MODE|Trino|Athena|SERVING_BACKEND|ClickHouse" docs .env.example src/serving` matches the intended story.

## Done When

- [x] Each subagent has a disjoint write scope and reports changed files.
- [x] `git status --short` contains only intended files.
- [x] `git diff --check` passes.
- [x] Full gates pass before commit: backend pytest, TS unit tests, TS typecheck, and TS build if frontend/package source changed.

## Completion Evidence

- Backend full suite: `.venv\Scripts\python.exe -m pytest -p no:schemathesis -q --basetemp .tmp\pytest-basetemp-codex-continue -o cache_dir=.tmp\pytest-cache-codex-continue` -> `749 passed, 4 skipped in 362.47s`.
- TypeScript SDK: `npm run typecheck`, `npm run test:unit` -> `45 passed`, and `npm run build`.
- Compose/config/docs: `docker compose -f docker-compose.prod.yml config --quiet`, `python scripts\generate_contracts.py --check`, `git diff --check`.
