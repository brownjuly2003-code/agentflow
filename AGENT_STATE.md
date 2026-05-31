# Agent State

Updated: 2026-05-30

## Current Project State

- Project: AgentFlow, a Python 3.11 real-time data platform with FastAPI serving, ingestion/processing pipelines, Python SDK, TypeScript SDK, Docker, Helm, Kubernetes, and Terraform support.
- Branch: `main...origin/main`
- Backlog correction base HEAD: `3080275`
- Verified local code HEAD before this state-refresh commit: `0cdac067f5d23163259100030fd0f137bf0510e5` (`0cdac06`)
- Git status at refresh start: clean tracked-file status via `git status --short --branch --untracked-files=no`; branch is even with `origin/main`. Full status no longer reports the old access-denied temp-directory warnings after `.gitignore` root-anchors the locked local temp directories.
- State refresh scope: durable autonomous closeout docs and next-session plan only: `AGENT_STATE.md`, `docs/SESSION_HANDOFF.md`, and `next-session-autonomous-local-plan.md`; no product code, deployment, Docker, Terraform, secrets, external accounts, paid APIs, production data, runtime databases, or AWS calls.
- File count at refresh start: `git ls-files` reports 906 tracked files. Frontend bundle size, build artifact size, and i18n key count are not applicable to this state-only refresh.

## Available Runtime

- pi CLI: available at `C:\Users\uedom\AppData\Roaming\npm\pi.ps1`, but current local `pi` planner runs fail without an API key and are not used by the scheduled task.
- codex CLI: available at `C:\Users\uedom\AppData\Roaming\npm\codex.ps1`
- Runner: `scripts/autopilot.ps1`, default planner `codex`
- Scheduler: installed as `AgentFlow Local Autopilot` with `-Planner codex -ExitZeroOnBlocked -Commit`; preview without `-Install` must not modify scheduler state.
- Docker Desktop / Docker daemon: do not start on this Windows workstation. Docker has been observed to hang local processes here; Docker-heavy validation belongs on the Mac runner or CI.
- iMac Docker host: `julia@192.168.1.133` is reachable over SSH; Lima `docker` instance is running with Docker Engine `29.5.2`; Docker Compose CLI plugin `v5.1.4` is installed under the user Docker CLI plugins; checkout path is `/Users/julia/agentflow-docker-check`. GitHub repo self-hosted Actions runners currently report `total=0`, so this is an SSH-operated Mac host, not a registered GitHub Actions runner. Python 3.11 is available for repo verification through `/Users/julia/agentflow-docker-check/.venv-mac-docker`.

## Operating Mode

Status: READY_WITH_GUARDRAILS

The autopilot handoff files are project artifacts. `.autopilot/` is local runtime state and remains ignored. Do not run deploys, Terraform apply, production scripts, secret rotation, package publishing, paid external API calls, or live account operations.

The guarded local autopilot has been hardened through HEAD `c43111c`: it defaults to the Codex planner, treats active concurrent locks as a clean no-work exit, accepts both inline and markdown `Commit Allowed` gates, exits cleanly for scheduled no-task blockers, and forbids HEAD-only handoff churn as an autonomous task. A real scheduled-mode run wrote `.autopilot/BLOCKED.md` because no bounded safe local task remained.

The 2026-05-29 local refresh did not add owner-provided external evidence. The 2026-05-30 external-outreach restart added two accepted public-form contact submissions for PMF/customer discovery and several non-counting attempts documented in `docs/customer-discovery-tracker.md`. This is outreach evidence only; PMF/pricing remains blocked until real replies, scheduled/completed interviews, WTP/pricing evidence, LOI/invoice/procurement artifacts, or first-paying-customer signals exist. External AWS/Terraform is now explicitly out of scope for this project unless the operator later reintroduces a budget, account, and foreign-card/payment path; do not cite missing AWS apply as a project deficiency or recurring blocker. Production CDC, production benchmark, external pen-test, and real production deployment gates remain blocked or not applicable.

Operator budget constraint recorded on 2026-05-30: the operator has no foreign payment card for AWS signup and no AWS budget. The replacement path for the DV2/X5 demo is not AWS; use the already documented S3-compatible cold-tier story with HF Datasets or Backblaze B2 for anonymized parquet. Raw X5/Kaggle source data should not be committed to git, and any public dataset repo should contain only license-compatible derived/anonymized parquet plus a dataset card linking back to the original Kaggle source.

The 2026-05-30 generated external gate pack is checked in at `docs/operations/generated-external-gate-pack-2026-05-30.md`. It covers zero-budget AWS/Terraform posture, synthetic production CDC intake, five generated PMF interviews, generated pricing/WTP review, synthetic production-hardware benchmark report shape, and simulated external pen-test attestation. This closes the generated/modelled deliverable only; it does not close any real external evidence gate.

The 2026-05-30 local policy update marks this Windows workstation as no-Docker. Local broad pytest must use `SKIP_DOCKER_TESTS=1`; Docker Desktop, Docker compose/build, kind/Helm live validation, chaos tests, and Docker-dependent full pytest must run on the Mac runner or in CI before claiming Docker-heavy coverage.

A 2026-05-30 autonomous Mac Docker verification on iMac `julia@192.168.1.133` checked out `origin/main` at historical HEAD `ffeb423` and installed the user-local Docker Compose CLI plugin because Docker Engine was present but `docker compose` was initially missing. Direct `docker build -f Dockerfile.api -t agentflow-api:mac-docker-smoke-ffeb423 .` passed. `docker compose -p agentflow-e2e-mac -f docker-compose.e2e.yml up -d --build --wait agentflow-api` passed: Redis, Postgres, Kafka, and API containers reached Docker `Healthy`, and `curl http://127.0.0.1:8000/v1/health` returned with `kafka:healthy` and `duckdb_pool:healthy`. The app aggregate status remained `unhealthy` because the e2e compose stack intentionally does not include Flink or Iceberg and no pipeline events had been produced. `docker compose ... down -v` cleanup ran and only the pre-existing `hq-demo` kind containers remained. Full Docker-capable pytest was not run on the Mac because only system Python 3.9 is currently available there; install/use Python 3.11 before running pytest-based Docker gates outside CI.

A follow-up Mac pytest-based compose smoke on 2026-05-30 found the webhook callback path failing on Lima because `host.docker.internal:host-gateway` shadows Lima's native host DNS. Commit `677de80` keeps Linux/CI on `host.docker.internal` but uses `host.lima.internal` for compose-mode callback URLs on Darwin, while preserving an explicit `AGENTFLOW_E2E_CALLBACK_HOST` override. On iMac, `/Users/julia/agentflow-docker-check/.venv-mac-docker/bin/python -m pytest tests/e2e/test_smoke.py -v --tb=short -p no:schemathesis --basetemp .tmp/mac-e2e-smoke-basetemp -o cache_dir=.tmp/mac-e2e-smoke-cache` with `AGENTFLOW_E2E_MODE=compose` and `AGENTFLOW_E2E_TIMEOUT=180` passed with `10 passed in 121.10s`; cleanup left only the pre-existing `hq-demo` kind containers.

The 2026-05-30 Codex audit remediation has closed all locally actionable findings from ignored `audit_codex_30_05_26.md`: `0ea3da6` normalizes FastAPI-owned `ValidationError.input/ctx` fields in `scripts/export_openapi.py`, regenerates `docs/openapi.json`, and adds `tests/unit/test_export_openapi.py`; `a261b95` refreshes README and `docs/dv2-multi-branch/RELEASE_STATUS.md` to `v1.4.0` registry reality and documents that GitHub Release objects currently stop at `v1.1.0`; `397925c` refreshed durable state after the first P1 fixes; `672c8fd` bounds streamed request bodies without `Content-Length`; `c61a28c` removes mojibake from the DuckDB explain-plan scrubber and pins box-drawing parsing; `dce7115` refreshes `docs/quality.md` through a no-Docker quality-report mode; `8c96128` ignores locked local temp roots without hiding project outputs; and `7b0f924`/`65863f8` make `docker-compose.prod.yml` reuse `Dockerfile.api` while carrying the prior security pins into the runtime image.

Code HEAD `65863f8` had GitHub push green for CI, Contract Tests, Security Scan, E2E Tests, and Staging Deploy. Push Load Test run `26677145590` failed with broad p99 slowdown and no functional request failures; artifacts were compared against the previous green `8c96128` run and only latency shifted. Per `docs/runbooks/load-test-regression.md`, two subsequent manual Load Test runs on the same SHA, `26677294150` and `26677355752`, both completed successfully, so this is recorded as runner variance. Follow-up state closeout commit `93b04b7` was pushed with CI, Security Scan, Load Test, E2E Tests, Staging Deploy, and manually dispatched Contract Tests all green. The failed `65863f8` push Load Test run remains in GitHub history.

A 2026-05-30 autonomous external-gate recheck found the historical AWS OIDC/Terraform apply path unconfigured: `AWS_REGION=us-east-1` was the only repo variable, `AWS_TERRAFORM_ROLE_ARN` and workflow-expected `infrastructure/terraform/environments/*.tfvars` files were absent, and `gh run list --workflow terraform-apply.yml` reported no `Terraform Apply` runs. This is now historical context only. Because the operator has no AWS budget or foreign-card/payment path, do not repeat AWS readiness probes or present AWS absence as a live gap unless the operator explicitly reopens AWS with budget/account details.

The 2026-05-30 autonomy process update adds `docs/operations/autonomous-compact-safe-process.md` as the durable rule for no-prompt local continuation, compact-safe recovery, anti-repeat checks, admin delegation, local commit autonomy, and remote/destructive boundaries. Local commits are at the agent's discretion after scoped verification. The operator has granted standing authorization for ordinary `git push origin main` from the human-agent autonomous session after clean tracked status and `git diff --check`; force-push/deploy/release/publish/Terraform apply/scheduler/env/destructive actions still require an explicit latest instruction naming the action and target.

The 2026-05-30 autonomous local follow-up after the Codex audit closeout is complete through HEAD `0759fc6`: `1b122cf` pinned the container PR smoke job name and unit coverage, `20fbba3` documented the non-required `build-smoke` branch-protection gap, `ed50b2d` clarified the DV2 recording-day cluster resume sequence, `0e47794` and `5926d8e` exposed Python SDK version/deprecation/latest header accessors, `c2f4db5` documented those accessors in the API reference, and `0759fc6` clarified the TLS termination boundary in the security audit. Current GitHub evidence on `0759fc6`: CI, Security Scan, Load Test, E2E Tests, Staging Deploy, and manually dispatched Contract Tests all completed successfully. No Docker, AWS, Terraform, deploy, publish, paid service, secret, or production operation was used.

For a compact-safe next session, rebuild context from checked-in files instead of relying on chat memory: read `AGENT_STATE.md`, `docs/SESSION_HANDOFF.md`, `docs/operations/local-verification-matrix.md`, `AUTOPILOT.md`, `docs/operations/autonomous-compact-safe-process.md`, `BACKLOG.md`, and `.autopilot/BLOCKED.md` if present. Then use `next-session-autonomous-local-plan.md` as the active cold-start checklist. A continuation prompt can be: `D:\DE_project. Продолжай автономно без Docker на этой Windows-машине. Восстанови состояние из checked-in docs, не опирайся на неполный chat compact, закрывай текущий dirty WIP первым и используй только no-Docker локальные проверки. Не спрашивай что дальше, пока есть безопасный локальный атомарный пункт; не повторяй заблокированную семью без нового evidence.`

The 2026-05-05 closeout was interrupted by an explicit audit-remediation request. Commit `adb9c8e` records the first five locally verifiable Kimi audit fixes, Codex+Kimi synthesis under `res/codex/`, M1/M2 SQL static-analysis gate narrowing, L6 SBOM artifact generation, M7 staging rollback safety, and the first narrow M3 mypy strict slice for `src.quality.validators.*`. Commit `afbe643` records the M8 scoped validators coverage gate. Tasks 18-22 stay blocked until real owner-provided evidence is supplied.

The 2026-05-06 local audit-gates session started at HEAD `8f5eadd`, branch
`main...origin/main [ahead 1]`, with `git ls-files` count `702`. The handoff
count in `next-session-free-local-audit-gates-plan.md` was stale by more than
10%, so targets were treated as advisory. Local remediation added H3/M4 Helm
single-writer and existing-secret support, H6 optional DuckDB encrypted attach,
M9 hash-chained audit JSONL export, L7 digest-only GitHub/Sigstore workflow
skeleton, H4 no-apply Terraform preflight, and H5 internal security evidence
template. H4, H5, L7 real signing, and external immutable retention stay
evidence-pending until owner-supplied artifacts exist.

The 2026-05-06 external evidence-gates continuation started from pushed HEAD
`1683d5d`, branch `main...origin/main`, with `git ls-files` count `710`.
Historical recheck found H4 unconfigured (`AWS_REGION` only, no
`AWS_TERRAFORM_ROLE_ARN`, no local AWS credential hints, no `aws`/`terraform`
CLI, no real tfvars, no Terraform Apply runs). That AWS path is now superseded
by the 2026-05-30 no-budget/no-card decision and is not an active blocker. H5
still blocked (no external tester/report/attestation packet), and M9 external
immutable retention still blocked if claimed beyond local hash-chain support
(no WORM/Object Lock/SIEM policy, write proof, or readback evidence).

## Last Verified Gates

- Agent query router strict mypy slice through code HEAD `0cdac06` on 2026-05-31:
  - `0cdac06` promotes `src.serving.api.routers.agent_query` (LLM-facing
    explain/query/entity/metric/catalog API surface) to
    `disallow_untyped_defs = true`. The gaps were typed version-transform
    payloads, `_metric_tables`'s dynamic catalog parameter, and five route
    handler return annotations. Pure annotation; route behavior is unchanged.
  - Tests-first: `tests/unit/test_typing_policy.py::test_agent_query_router_is_a_strict_mypy_slice` (red→green).
  - Local verification: `python -m mypy src --config-file pyproject.toml` clean
    on 99 files; `python -m pytest tests/unit/test_typing_policy.py
    tests/unit/test_agent_query_async.py tests/unit/test_cache.py
    tests/unit/test_entity_cache.py tests/unit/test_masking.py
    tests/unit/test_versioning.py tests/integration/test_logical_correctness.py
    tests/integration/test_tenant_isolation.py -q -p no:schemathesis` passed
    with 72 tests; `SKIP_DOCKER_TESTS=1 python -m pytest tests/unit -p
    no:schemathesis --continue-on-collection-errors` passed with 599 passed, 1
    skipped; `python scripts/export_openapi.py --check` passed; targeted `ruff
    check` / `ruff format --check` and `git diff --check` passed.
  - GitHub evidence on `0cdac06`: CI, Contract Tests, E2E Tests, Load Test,
    Security Scan, and Staging Deploy all completed successfully.
- Contracts router strict mypy slice through code HEAD `84c63dc` on 2026-05-30:
  - `84c63dc` promotes `src.serving.api.routers.contracts` (schema governance:
    version lookup, diff, latest stable lookup, and candidate validation) to
    `disallow_untyped_defs = true`. The gaps were `_get_registry`'s dynamic
    `app.state.catalog.contract_registry` return and five route-handler return
    annotations. Pure annotation; route behavior is unchanged.
  - The same commit regenerates `docs/openapi.json` for the expected FastAPI
    response schema drift from those return annotations.
  - Tests-first: `tests/unit/test_typing_policy.py::test_contracts_router_is_a_strict_mypy_slice` (red→green).
  - Local verification: `python -m mypy src --config-file pyproject.toml` clean
    on 99 files; `python -m pytest tests/unit/test_typing_policy.py
    tests/integration/test_contracts.py tests/unit/test_schema_evolution.py -q
    -p no:schemathesis` passed with 37 tests; `SKIP_DOCKER_TESTS=1 python -m
    pytest tests/unit -p no:schemathesis --continue-on-collection-errors`
    passed with 598 passed, 1 skipped; `python scripts/export_openapi.py
    --check` passed; `python -m pytest tests/unit/test_export_openapi.py
    tests/contract -q -p no:schemathesis` passed with 18 tests and 104
    warnings; targeted `ruff check` / `ruff format --check` and `git diff
    --check` passed.
  - GitHub evidence on `84c63dc`: CI, Contract Tests, E2E Tests, Load Test,
    Security Scan, and Staging Deploy all completed successfully.
- Alerts router strict mypy slice through code HEAD `5f61fd3` on 2026-05-30:
  - `5f61fd3` promotes `src.serving.api.routers.alerts` (tenant-scoped alert
    rule management, test dispatch, delete, update, and history read API) to
    `disallow_untyped_defs = true`. The gaps were `_tenant`'s dynamic
    `app.state` return, six route-handler return annotations, and a cast for
    `AlertDispatcher.send_test_alert()` through the API router boundary. Pure
    annotation; route behavior is unchanged.
  - The same commit regenerates `docs/openapi.json` for the expected FastAPI
    response schema drift from those return annotations.
  - Tests-first: `tests/unit/test_typing_policy.py::test_alerts_router_is_a_strict_mypy_slice` (red→green).
  - Local verification: `python -m mypy src --config-file pyproject.toml` clean
    on 99 files; `python -m pytest tests/unit/test_typing_policy.py
    tests/integration/test_alerts.py -q -p no:schemathesis` passed with 20
    tests; `SKIP_DOCKER_TESTS=1 python -m pytest tests/unit -p
    no:schemathesis --continue-on-collection-errors` passed with 597 passed, 1
    skipped; `python scripts/export_openapi.py --check` passed; `python -m
    pytest tests/unit/test_export_openapi.py tests/contract -q -p
    no:schemathesis` passed with 18 tests and 104 warnings; targeted `ruff
    check` / `ruff format --check` and `git diff --check` passed.
  - GitHub evidence on `5f61fd3`: CI, Contract Tests, E2E Tests, Load Test,
    Security Scan, and Staging Deploy all completed successfully.
- Webhooks router strict mypy slice through code HEAD `45d3fc5` on 2026-05-30:
  - `452d120` promotes `src.serving.api.routers.webhooks` (tenant-scoped
    callback registration, test delivery, unsubscribe, and delivery-log read
    API) to `disallow_untyped_defs = true`. The gaps were `_tenant`'s dynamic
    `app.state` return, five route-handler return annotations, and a
    `WebhookDispatcher` cast for the dynamically typed `app.state` dispatcher.
    Pure annotation; route behavior is unchanged.
  - `45d3fc5` regenerates `docs/openapi.json` for the expected FastAPI response
    schema drift from those return annotations. The first pushed code commit
    (`452d120`) failed Contract Tests only at `python scripts/export_openapi.py
    --check`; the generated OpenAPI fix commit passed Contract Tests.
  - Tests-first: `tests/unit/test_typing_policy.py::test_webhooks_router_is_a_strict_mypy_slice` (red→green).
  - Local verification: `python -m mypy src --config-file pyproject.toml` clean
    on 99 files; `python -m pytest tests/unit/test_typing_policy.py
    tests/integration/test_webhooks.py -q -p no:schemathesis` passed with 21
    tests; `SKIP_DOCKER_TESTS=1 python -m pytest tests/unit -p
    no:schemathesis --continue-on-collection-errors` passed with 596 passed, 1
    skipped; `python scripts/export_openapi.py --check` passed; `python -m
    pytest tests/unit/test_export_openapi.py tests/contract -q -p
    no:schemathesis` passed with 18 tests and 104 warnings; targeted `ruff
    check` / `ruff format --check` and `git diff --check` passed.
  - GitHub evidence on `45d3fc5`: CI, Contract Tests, E2E Tests, Load Test,
    Security Scan, and Staging Deploy all completed successfully. `gh pr list
    --state open` empty before the slice.
- Dead-letter router strict mypy slice through HEAD `e92a6eb` on 2026-05-30:
  - `e92a6eb` promotes `src.serving.api.routers.deadletter` (the operator-facing
    recovery API: list / detail / stats / replay / dismiss) to
    `disallow_untyped_defs = true`. It sits over the same `dead_letter_events`
    table the strict-typed `event_replayer` / `outbox` slices manage, so this
    completes the dead-letter handling surface end to end. Seven gaps: `_conn`'s
    return (a `cast(duckdb.DuckDBPyConnection, ...)` — `app.state` is dynamically
    typed, so a bare `-> DuckDBPyConnection` would trip `warn_return_any`),
    `_decode_payload`'s `payload` → `object`, and the five route-handler return
    types (their Pydantic response models). Pure annotation. Second bounded
    `src/serving/api` slice (after `middleware`).
  - Tests-first: `tests/unit/test_typing_policy.py::test_deadletter_router_is_a_strict_mypy_slice` (red→green).
  - `python -m mypy src --config-file pyproject.toml`: clean on 99 files. `python -m pytest tests/unit/test_typing_policy.py -p no:schemathesis`: 11 passed. `ruff check` / `ruff format --check`: passed. `git diff --check`: passed (no EOL flip). `SKIP_DOCKER_TESTS=1 python -m pytest tests/unit -p no:schemathesis --continue-on-collection-errors`: 595 passed, 1 skipped.
  - GitHub evidence on `e92a6eb`: CI, Contract Tests, E2E Tests, Load Test, Security Scan, and Staging Deploy all completed successfully (the push hit a transient `Could not resolve host: github.com` DNS error — the v2RayTun-proxy signature — and succeeded on one retry). `gh pr list --state open` empty.
- First `src/serving/api` bounded slice — request middleware — through HEAD `4ad01fd` on 2026-05-30:
  - `4ad01fd` promotes `src.serving.api.middleware.*` (correlation logging +
    HTTP metrics + tracing — the per-request observability path) to
    `disallow_untyped_defs = true`. This is the first bounded slice into the
    large `src/serving/api` surface, done per the plan's "bounded,
    individually-verified slices" rule rather than a whole-package grind. The
    two gaps were the middleware-factory return types
    (`build_correlation_middleware`, `build_metrics_middleware`), each annotated
    as the ASGI-style `Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]` they return; `tracing.py` was already clean. Pure annotation.
  - Tests-first: `tests/unit/test_typing_policy.py::test_api_middleware_is_a_strict_mypy_slice` (red→green).
  - `python -m mypy src --config-file pyproject.toml`: clean on 99 files. `python -m pytest tests/unit/test_typing_policy.py -p no:schemathesis`: 10 passed. `ruff check` / `ruff format --check`: passed (the wrapped return annotation formats clean). `git diff --check`: passed (no EOL flip). `SKIP_DOCKER_TESTS=1 python -m pytest tests/unit -p no:schemathesis --continue-on-collection-errors`: 594 passed, 1 skipped.
  - GitHub evidence on `4ad01fd`: CI, Contract Tests, E2E Tests, Load Test, Security Scan, and Staging Deploy all completed successfully. `gh pr list --state open` empty.
- Processing-pipeline + outbox strict mypy slices through HEAD `0953fcc` on 2026-05-30:
  - `98a9ed5` promotes `src.processing.local_pipeline` (the zero-infra
    generate→validate→enrich→DuckDB demo path) to `disallow_untyped_defs = true`
    — five missing `-> None` returns; params were already typed and the DuckDB
    handle is a function-local, so no Optional-attribute cascade. Pure
    annotation.
  - `0953fcc` promotes `src.processing.outbox` (the transactional outbox,
    at-least-once delivery guarantee). The `DuckDBPyConnection | None` handle
    (nulled in `close()`) is now reached through a `_connection` property, so a
    use-after-close raises `RuntimeError("OutboxProcessor connection is
    closed")` instead of an `AttributeError` on `None` (a small robustness gain,
    not just typing). Also annotated `ensure_outbox_table`'s `conn`,
    `_process_row`'s `row`, `_decode_payload`'s `payload`, and the nested Kafka
    `on_delivery` callback. With these two, all of `src/processing` except the
    PR-#23-gated `flink_jobs` is strict-typed.
  - Tests-first: typing-policy assertions for both modules (red→green) plus a
    new `tests/unit/test_outbox_connection_guard.py` (empty-poll returns 0,
    use-after-close raises, idempotent close). `local_pipeline` behavior is the
    demo entrypoint; `outbox` replay behavior is also covered by
    `tests/integration/test_outbox.py`.
  - `python -m mypy src --config-file pyproject.toml`: clean on 99 files (both slices). `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_outbox_connection_guard.py -p no:schemathesis`: passed. `ruff check` / `ruff format --check`: passed. `git diff --check`: passed (no EOL flip either commit). `SKIP_DOCKER_TESTS=1 python -m pytest tests/unit -p no:schemathesis --continue-on-collection-errors`: 589 passed / 1 skipped (`98a9ed5`) then 593 passed / 1 skipped (`0953fcc`).
  - GitHub evidence: `98a9ed5` all six workflows (CI, Contract Tests, E2E Tests, Load Test, Security Scan, Staging Deploy) completed successfully; `0953fcc` likewise all six green. `gh pr list --state open` empty.
- Event-replayer strict mypy slice through HEAD `8a50ab6` on 2026-05-30:
  - `8a50ab6` promotes `src.processing.event_replayer` (exact module, not a
    package glob — the `src.processing.*` neighbours `outbox` / `local_pipeline`
    / `flink_jobs` stay untyped/own-override) to `disallow_untyped_defs = true`.
    The dead-letter replay path re-emits failed events through the transactional
    outbox; keeping it annotated guards a delivery-correctness surface. Four
    untyped params annotated (`ensure_dead_letter_table`'s `conn` and
    `EventReplayer.__init__`'s `conn` → `duckdb.DuckDBPyConnection` with a new
    `import duckdb`; `_decoded_payload`'s `payload` → `object`; the nested Kafka
    `on_delivery(err, msg)` → `object`). Pure annotation change — no behavior
    change and no latent bug surfaced (the `fetchone()` lookup in `_load_row`
    was already `None`-guarded). `src.processing.outbox` was assessed and
    deferred: its connection is `DuckDBPyConnection | None` (set to `None` in
    `close()`), so typing it cascades `None`-access checks across every method —
    not a bounded annotation-only slice.
  - Tests-first: added `tests/unit/test_typing_policy.py::test_event_replayer_is_a_strict_mypy_slice`
    (red before the pyproject override, green after). Replay behavior is covered
    by the existing `tests/integration/test_outbox.py` + `test_logical_correctness.py`.
  - `python -m mypy src --config-file pyproject.toml`: clean on 99 files. `python -m pytest tests/unit/test_typing_policy.py -p no:schemathesis`: 7 passed. `ruff check` / `ruff format --check` on the touched files: passed. `git diff --check`: passed (no EOL flip this commit). `SKIP_DOCKER_TESTS=1 python -m pytest tests/unit -p no:schemathesis --continue-on-collection-errors`: 588 passed, 1 skipped.
  - GitHub evidence on `8a50ab6`: CI, Contract Tests, E2E Tests, Load Test, Security Scan, and Staging Deploy all completed successfully. `gh pr list --state open` empty.
- Orchestration-DAGs strict mypy slice + DuckDB `fetchone()` None-safety fix through HEAD `80316fb` on 2026-05-30:
  - `80316fb` promotes `src.orchestration.dags.*` to a strict mypy slice
    (`disallow_untyped_defs = true`). Annotating the six previously-untyped
    `daily_batch` defs (`_get_conn` + the five Dagster `@asset` functions)
    surfaced a real latent bug: `DuckDBPyConnection.fetchone()` is typed
    `tuple[Any, ...] | None`, and the `COUNT(*)` lookups in
    `daily_product_metrics` / `daily_quality_report` indexed `[0]` on a
    possibly-`None` result (would raise if a query returned no row). They now
    fall back to `0`.
  - Tests-first: added `tests/unit/test_typing_policy.py::test_orchestration_dags_are_a_strict_mypy_slice`
    (red before the pyproject override, green after) and a new
    `tests/unit/test_daily_batch_dag.py` (4 tests: None-safety happy paths via
    a file-backed DuckDB + local-mode no-op assertions for the previously
    untested DAG assets).
  - `python -m mypy src --config-file pyproject.toml`: clean on 99 files
    (the full run, not `--follow-imports=skip`, is what caught the
    `tuple[Any, ...] | None` indexing). `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_daily_batch_dag.py -p no:schemathesis`: 10 passed. `ruff check` / `ruff format --check` on the touched files: passed. `git diff --check`: passed (the Edit tool re-flipped `daily_batch.py` to CRLF — Gotcha 1 — normalized back to LF with an atomic byte-level rewrite before staging). `SKIP_DOCKER_TESTS=1 python -m pytest tests/unit -p no:schemathesis --continue-on-collection-errors`: 587 passed, 1 skipped.
  - GitHub evidence on `80316fb`: CI, Contract Tests, E2E Tests, Load Test, Security Scan, and Staging Deploy all completed successfully. `gh pr list --state open` empty.
- Strict-typing cadence extended + bandit-baseline drift fix through HEAD `dd0a46d` on 2026-05-30:
  - `30e20a7` promotes `src.serving.semantic_layer.*` to a strict mypy slice
    (three `DataCatalog` return-type annotations). `346bf64` promotes
    `src.serving.backends.*` (the two `scalar()` methods typed `-> Any` to match
    the `ServingBackend` ABC) and normalizes `clickhouse_backend.py` from its
    historical CRLF to LF. `dd0a46d` fixes the fallout (below).
  - **Gotcha 1 — Edit-tool EOL flips.** On this repo the Edit tool rewrote
    `clickhouse_backend.py` to CRLF and at one point truncated it to 0 bytes
    (ruff/mypy "pass" on an empty `.py`, masking it). The repo has no
    `.gitattributes` and mixed EOL (catalog.py was LF, clickhouse was CRLF).
    Fix pattern: edit source with a single atomic byte-level Python
    read-into-variable → transform → write (never chained
    `open(wb).write(open(rb).read())`), and after any source edit check
    `CRLF` count + `git diff --check` + that staged blob size is non-empty.
  - **Gotcha 2 — bandit baseline is line-keyed.** `scripts/bandit_diff.py`
    `_issue_key` is `(test_id, filename, line_number)`. Adding the
    `from typing import Any` import shifted the audited `urlopen()` B310 finding
    from line 69 to 70, so both the Security Scan workflow and the CI
    `test_bandit_diff` unit test flagged it as a new finding. `dd0a46d` updates
    `.bandit-baseline.json` line 69 → 70. Any line-shifting edit to a file with
    a baseline finding needs the baseline refreshed.
  - `python -m mypy src --config-file pyproject.toml`: clean on 99 files.
    `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_bandit_diff.py tests/unit/test_duckdb_backend_sql_hardening.py tests/unit/test_clickhouse_backend.py -p no:schemathesis`: passed. `ruff check` / `ruff format --check` / `git diff --check`: passed. Local `bandit -r src sdk --ini .bandit ...` + `scripts/bandit_diff.py`: "No new findings".
  - GitHub evidence: `30e20a7` six workflows green; `346bf64` had CI + Security Scan red from the baseline drift; `dd0a46d` green on CI, E2E, Load Test, Security Scan, Staging Deploy (Contract Tests path-filtered on a baseline-only change, required check carries the prior SUCCESS — Lesson 4).
- Monitors strict mypy slice + tombstone fix through HEAD `3e7434b` on 2026-05-30:
  - `fix(monitors): skip tombstone records + make monitors a strict mypy slice`
    promotes `src.quality.monitors.*` to `disallow_untyped_defs = true`. Typing
    `_process_message(msg: Message)` surfaced two latent bugs:
    `Message.value()` is `bytes | None` (`.decode()` would crash on a
    tombstone) and `.topic()` is `str | None` (used as a dict key / metric
    label). The handler now skips such records with a `reason="empty_message"`
    warning.
  - `python -m mypy src --config-file pyproject.toml`: clean on 99 files.
  - `python -m pytest tests/unit/test_freshness_monitor.py tests/unit/test_typing_policy.py --cov=src.quality.monitors.freshness_monitor --cov-fail-under=90`: 14 passed, freshness_monitor at 100% coverage (two new tombstone/no-topic tests). `ruff check` / `ruff format --check` / `git diff --check`: passed.
  - GitHub evidence on `3e7434b`: CI, Contract Tests, E2E Tests, Load Test, Security Scan, and Staging Deploy all completed successfully.
- Auth strict mypy slice through HEAD `f977317` on 2026-05-30:
  - `refactor(auth): promote auth package to a strict mypy slice` sets
    `disallow_untyped_defs = true` for `src.serving.api.auth.*`. The only gap
    was `AuthManager.__init__`'s `time_source` parameter, now typed
    `Callable[[], float]`. `tests/unit/test_typing_policy.py` gains a
    `test_auth_package_is_a_strict_mypy_slice` assertion (red before the
    pyproject override, green after).
  - `python -m mypy src --config-file pyproject.toml`: `Success: no issues found in 99 source files`.
  - `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_auth.py tests/unit/test_auth_hashed_key_guidance.py -p no:schemathesis`: passed (16 tests). `ruff check` / `ruff format --check` on touched files passed. `git diff --check`: passed.
  - GitHub evidence on `f977317`: CI, Contract Tests, E2E Tests, Security Scan, and Staging Deploy completed successfully. The push Load Test run `26686620700` failed with a broad uniform p99 inflation (all six endpoints ~1900-2200 ms, 0.00% functional failures) — the documented runner-variance signature, not a code regression (the change is type-only). Per `docs/runbooks/load-test-regression.md` the run was re-run on the same SHA and completed successfully.
- M-C4 hashed-key guidance enforcement through HEAD `e444ecf` on 2026-05-30:
  - `feat(auth): warn when hashed-key count exceeds M-C4 soft limit` adds
    `HASHED_KEY_SOFT_LIMIT = 10` in `src/constants.py`, a
    `hashed_key_count_exceeds_guidance` warning in `AuthManager.load()`, and
    `tests/unit/test_auth_hashed_key_guidance.py` (3 tests). Turns the
    previously docs-only M-C4 guidance into a runtime signal. CHANGELOG and
    `docs/runbooks/auth-401-spike.md` updated.
  - Red/green: the warning test failed before the `load()` change (no warning
    emitted), then passed after. Captured via `structlog.testing.capture_logs`
    because `configure_logging()` (stdlib factory) is not active in unit tests.
  - `python -m pytest tests/unit/test_auth.py tests/unit/test_auth_manager_memory_bounds.py tests/unit/test_auth_hashed_key_guidance.py -p no:schemathesis`: passed with 19 tests.
  - `SKIP_DOCKER_TESTS=1 python -m pytest tests/unit -p no:schemathesis --continue-on-collection-errors`: 571 passed, 1 skipped. Two pre-existing local-`.venv` artifacts unrelated to this change: `test_x5_retail_hero_loader.py` collection error (no `pandas` installed in `.venv`) and `test_version.py::test_distribution_version_matches_sdk_version` (installed `agentflow-client` metadata is `1.3.0` vs `__version__` `1.4.0` — the SDK was not reinstalled in this `.venv` after the v1.4.0 bump; the Python313/Python312 shadow). CI installs full deps and is green.
  - `python -m ruff check` / `python -m ruff format --check` on the touched files: passed. `python -m mypy src/serving/api/auth/manager.py src/constants.py --config-file pyproject.toml --no-incremental`: `Success: no issues found`. `git diff --check`: passed.
  - GitHub evidence on `e444ecf`: CI, Contract Tests, E2E Tests, Load Test, Security Scan, and Staging Deploy all completed successfully (owner-bypass push of the 12 required checks; all subsequently green). `gh pr list --state open` empty.
- Autonomous local follow-up through HEAD `0759fc6` on 2026-05-30:
  - `python -m pytest tests\unit\test_container_attestation_workflow.py -q -p no:schemathesis`: passed after tests-first coverage for the `build-smoke` job name.
  - `python -m pytest tests\unit\test_sdk_client.py tests\unit\test_sdk_async_client.py -q -p no:schemathesis`: passed with 42 tests after adding `last_deprecated`, `last_deprecation_warning`, and `last_latest_version` accessors.
  - `python -m ruff check` / `python -m ruff format --check` on the touched SDK and test slices: passed.
  - `python -m mypy sdk\agentflow\client.py sdk\agentflow\async_client.py --config-file pyproject.toml --follow-imports=skip --no-incremental --show-error-codes`: passed.
  - `git diff --check`: passed before each local commit and push.
  - GitHub evidence on current HEAD `0759fc6`: CI, Security Scan, Load Test, E2E Tests, Staging Deploy, and manually dispatched Contract Tests all completed successfully; `gh pr list --state open` returned no open PRs.
- Codex audit remediation on 2026-05-30 through HEAD `65863f8`:
  - `python scripts\export_openapi.py --check`: passed.
  - `python -m pytest tests\unit\test_export_openapi.py tests\contract -p no:schemathesis`: passed with 18 tests and 104 warnings.
  - `$env:SKIP_DOCKER_TESTS='1'; python -m pytest -p no:schemathesis --basetemp .tmp\codex-query-engine-full-basetemp -o cache_dir=.tmp\codex-query-engine-full-cache`: passed with 846 passed, 32 skipped, and 104 warnings.
  - `python -m pytest tests\unit\test_quality_report.py -q -p no:schemathesis`: passed with 8 tests.
  - `python scripts\quality_report.py --skip-docker --skip-dependency-scans`: passed and regenerated `docs/quality.md` with Safety/pip-audit/Trivy marked skipped for local no-Docker mode.
  - `python -m pytest tests\unit\test_contract_dependencies.py tests\unit\test_security_workflow.py tests\unit\test_container_attestation_workflow.py -q -p no:schemathesis`: passed with 22 tests.
  - `python -m ruff check` and `python -m ruff format --check` passed for each touched Python/test slice; `python -m mypy scripts\quality_report.py` passed for the quality-report change.
  - `git diff --check`: passed before each local commit and push.
  - GitHub evidence on current HEAD `65863f8`: push CI, Contract Tests, Security Scan, E2E Tests, and Staging Deploy completed successfully; Load Test push run `26677145590` failed from broad latency variance, then manual Load Test reruns `26677294150` and `26677355752` on the same SHA both completed successfully.
- Manual release-readiness sync verification on 2026-05-04:
  - `git rev-parse --short HEAD`: `3f88d74` at sync start.
  - `git diff --check`: passed.
  - `python -m pytest tests/unit -p no:schemathesis`: passed with 456 tests in 101.39s after the live-doc consistency updates.
  - Stale live-doc search excluding `docs/plans/codex-archive/**` and dated audit snapshots: only the guarded-autopilot example pattern remains.
  - `scripts/autopilot.ps1`: intentionally not run for the manual no-autopilot continuation.
- External gate evidence intake was completed after the manual continuation note:
  - `b8d2159`: added `docs/operations/external-gate-evidence-intake.md` and linked it from release docs.
  - `001694b`: added the project-local Pi skill at `.pi/skills/external-gate-evidence-intake`.
  - The intake checklist is documentation/workflow guidance only; it does not close AWS, production CDC, PMF/pricing, production benchmark, pen-test, or npm-token gates without real owner-provided evidence.
- Manual no-autopilot resume verification on 2026-05-04:
  - `git rev-parse --short HEAD`: `001694b`.
  - `git diff --check`: passed.
  - `git status --short --untracked-files=no`: expected manual docs/state changes only.
  - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-manual-continue-basetemp -o cache_dir=.tmp\codex-manual-continue-cache`: passed with 755 passed, 4 skipped, and 104 warnings.
  - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
  - `cd sdk-ts; npm run typecheck`: passed.
  - `powershell -ExecutionPolicy Bypass -File scripts\autopilot.ps1 -DryRun`: passed before the explicit no-autopilot continuation request; do not use autopilot for the current manual continuation.
- Manual access triage for backlog tasks 18-22 on 2026-05-04:
  - Task 18 AWS OIDC historical note: GitHub CLI was authenticated for repository inspection; AWS CLI and Terraform CLI were not available in `PATH`; `AWS_REGION` was the only repo variable; Terraform workflow jobs remained `if: false`; real tfvars were absent. Superseded on 2026-05-30 by the operator no-budget/no-card decision; do not treat as an active blocker.
  - Task 19 production CDC: no source owner, secret owner, source endpoint, table scope, private network path, Kubernetes Secret owner, monitoring owner, or rollback owner was available; no production connector was touched.
  - Task 20 PMF/pricing: no approved outbound account/session, warm intro thread, CRM/calendar artifact, interview evidence, pricing/WTP artifact, LOI, invoice, or first-paying-customer signal was available during the 2026-05-04 triage. On 2026-05-30, two public-form outreach submissions were accepted, but no replies, scheduled/completed interviews, pricing/WTP artifact, LOI, invoice, procurement artifact, or first-paying-customer signal exists yet.
  - Task 21 production benchmark: only historical local `.artifacts/benchmark/` files were found; no approved production-class host, budget, operator-run artifacts, fixture-safety confirmation, or publication approval was available.
  - Task 22 external pen-test: no third-party report, signed attestation, scope, severity summary, remediation map, retest status, or attestation owner was available; no external scanning or paid security service was run.
  - Each task handoff now includes a concise next operator packet describing the exact redacted owner-provided artifacts needed to unblock review.
  - Next-session task file written at `next-session-external-gates-operator-evidence-plan.md`.
- Manual no-autopilot evidence recheck on 2026-05-05:
  - `git rev-parse --short HEAD`: `10bc3c7`.
  - `git ls-files`: 673 tracked files.
  - `git status --short --branch`: clean tracked tree, `main...origin/main [ahead 21]`, with the known local access-denied warnings from old temp directories.
  - Task 18 AWS OIDC historical note: `gh variable list` reported only `AWS_REGION`; AWS CLI and Terraform CLI were not available; real staging/prod tfvars were absent. Superseded on 2026-05-30 by the operator no-budget/no-card decision.
  - Task 19 production CDC remains blocked: no approved production source owner packet or first-run evidence was available.
  - Task 20 PMF/pricing remains blocked for PMF/pricing claims: 2026-05-30 public-form outreach created two accepted submissions, but no real CRM reply, scheduled/completed interview, pricing/WTP, LOI, invoice, procurement, or paying-customer evidence is available.
  - Task 21 production benchmark remains blocked: no production-hardware artifacts or publication approval were available.
  - Task 22 external pen-test remains blocked: no third-party report or attestation packet was available.
  - Follow-up verification:
    - `git diff --check`: passed.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-continue-basetemp -o cache_dir=.tmp\codex-continue-cache`: passed with 755 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
- Kimi audit five-point local remediation on 2026-05-05:
  - Closed local audit items: Docker production install no longer uses editable root install; `.dockerignore` exists; MinIO images are pinned; Helm API image tag is `1.1.0`; request body size limit is enforced from the security policy.
  - Red/green verification: `tests/unit/test_security.py::test_request_size_limit_blocks_oversized_bodies` failed before the middleware change with `404`, then passed after implementation with `1 passed`.
  - Targeted verification:
    - `python -m pytest tests/unit/test_security.py tests/unit/test_helm_values_contract.py -p no:schemathesis --basetemp .tmp\codex-audit-targeted-basetemp -o cache_dir=.tmp\codex-audit-targeted-cache`: passed with 19 tests.
    - `docker compose config --quiet`: passed.
    - `docker build -f Dockerfile.api -t agentflow-api:audit-check .`: passed after preserving the built wheel filename for extras install.
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed.
    - `git diff --check`: passed.
  - Full verification:
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-audit-five-full-basetemp -o cache_dir=.tmp\codex-audit-five-full-cache`: passed with 756 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
- Codex+Kimi research synthesis and M1/M2 local remediation on 2026-05-05:
  - Integrated Codex artifacts under `res/codex/` with Kimi artifacts under `res/kimi/`; synthesis saved at `res/codex/codex_kimi_audit_synthesis_05_05_26.md`.
  - Closed local audit items: Ruff `S608` is no longer globally ignored, Bandit `B608` is no longer globally skipped, existing reviewed SQL construction is scoped through per-file Ruff ignores and inline Bandit `nosec B608` comments.
  - Red/green verification: `python -m pytest tests/unit/test_security_tooling_policy.py -p no:schemathesis --basetemp .tmp\codex-m1m2-policy-red-basetemp -o cache_dir=.tmp\codex-m1m2-policy-red-cache` failed before the config change, then passed after removing the global suppressions.
  - Focused verification:
    - `python -m ruff check src sdk integrations --select S608 --output-format concise`: passed.
    - `python -m ruff check src/ tests/`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-current.json`: passed with no new findings.
    - `python -m pytest tests/unit/test_bandit_diff.py tests/unit/test_security_tooling_policy.py -p no:schemathesis --basetemp .tmp\codex-m1m2-bandit-basetemp -o cache_dir=.tmp\codex-m1m2-bandit-cache`: passed with 6 tests.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 213 files already formatted.
    - `git diff --check`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`: passed with no new findings.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m1m2-final-full-basetemp -o cache_dir=.tmp\codex-m1m2-final-full-cache`: passed with 757 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
- L6 SBOM artifact generation on 2026-05-05:
  - Closed local audit item: `.github/workflows/security.yml` now generates `agentflow-api.cdx.json` in CycloneDX format from `agentflow-api:security-scan` and uploads it as `agentflow-api-sbom-cyclonedx`.
  - Red/green verification: `python -m pytest tests/unit/test_security_workflow.py -p no:schemathesis --basetemp .tmp\codex-l6-sbom-red-basetemp -o cache_dir=.tmp\codex-l6-sbom-red-cache` failed before the workflow change, then the targeted test passed after implementation.
  - Targeted verification:
    - `python -m pytest tests/unit/test_security_workflow.py -p no:schemathesis --basetemp .tmp\codex-l6-sbom-targeted-basetemp -o cache_dir=.tmp\codex-l6-sbom-targeted-cache`: passed with 1 test.
    - `python -m ruff check tests/unit/test_security_workflow.py`: passed.
    - `python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/security.yml').read_text(encoding='utf-8')); print('security workflow yaml ok')"`: passed.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 214 files already formatted.
    - `python -m pytest tests/unit/test_security_workflow.py tests/unit/test_security_tooling_policy.py tests/unit/test_bandit_diff.py -p no:schemathesis --basetemp .tmp\codex-l6-final-targeted-basetemp -o cache_dir=.tmp\codex-l6-final-targeted-cache`: passed with 7 tests.
    - `python -c "import pathlib, yaml; [yaml.safe_load(path.read_text(encoding='utf-8')) for path in pathlib.Path('.github/workflows').glob('*.yml')]; print('workflow yaml ok')"`: passed.
    - `git diff --check`: passed.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-l6-final-full-basetemp -o cache_dir=.tmp\codex-l6-final-full-cache`: passed with 758 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`: passed with no new findings.
- Freshness monitor scoped coverage gate on 2026-05-07:
  - Closed local audit item partially: `.github/workflows/ci.yml` now runs `tests/unit/test_freshness_monitor.py` with `--cov=src.quality.monitors.freshness_monitor --cov-fail-under=90`; broader global coverage remains at 60% until additional modules have enough evidence.
  - Tests-first verification:
    - `python -m pytest tests/unit/test_freshness_monitor.py --cov=src.quality.monitors.freshness_monitor --cov-fail-under=90 --basetemp .tmp\cov-fresh-baseline`: baseline before new coverage was 94% (4 lines missing: msg-is-None continue, valid-message dispatch, `__main__` block).
    - `python -m pytest tests/unit/test_freshness_monitor.py -v --tb=short --cov=src.quality.monitors.freshness_monitor --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\cov-fresh-green`: passed after one new test plus `# pragma: no cover` on the `__main__` entrypoint with total coverage 100.00%.
  - Targeted verification:
    - `python -m pytest tests/unit/test_coverage_policy.py tests/unit/test_freshness_monitor.py -v --tb=short -p no:schemathesis --basetemp .tmp\cov-fresh-policy`: passed with 11 tests.
    - `python -m ruff check tests/unit/test_freshness_monitor.py tests/unit/test_coverage_policy.py src/quality/monitors/freshness_monitor.py`: passed.
    - `python -m ruff format --check tests/unit/test_freshness_monitor.py tests/unit/test_coverage_policy.py src/quality/monitors/freshness_monitor.py`: passed (3 files already formatted).
    - `python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text(encoding='utf-8')); print('ci.yml yaml ok')"`: passed.
  - Final verification:
    - `python -m pytest tests/unit/ -p no:schemathesis --basetemp .tmp\full-unit-after-fresh -o cache_dir=.tmp\cache-full-unit`: passed with 486 tests.
- M8 scoped validators coverage gate on 2026-05-06:
  - Closed local audit item partially: `.github/workflows/ci.yml` now runs `tests/unit/test_validators.py` with `--cov=src.quality.validators --cov-fail-under=90`; broader global coverage remains at 60% until additional modules have enough evidence.
  - Tests-first verification:
    - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-validators-cov-basetemp -o cache_dir=.tmp\codex-m8-validators-cov-cache`: failed before new tests with total coverage 84.35%.
    - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-validators-cov-green-basetemp -o cache_dir=.tmp\codex-m8-validators-cov-green-cache`: passed after new tests with total coverage 100.00%.
  - CI-gate red/green verification:
    - `python -m pytest tests/unit/test_coverage_policy.py -p no:schemathesis --basetemp .tmp\codex-m8-ci-gate-red-basetemp -o cache_dir=.tmp\codex-m8-ci-gate-red-cache`: failed before the CI gate existed.
    - `python -m pytest tests/unit/test_coverage_policy.py -p no:schemathesis --basetemp .tmp\codex-m8-ci-gate-green-basetemp -o cache_dir=.tmp\codex-m8-ci-gate-green-cache`: passed after adding the CI gate.
  - Targeted verification:
    - `python -m ruff check tests\unit\test_coverage_policy.py tests\unit\test_validators.py`: passed.
    - `python -m pytest tests/unit/test_coverage_policy.py tests/unit/test_validators.py -p no:schemathesis --basetemp .tmp\codex-m8-final-targeted-basetemp -o cache_dir=.tmp\codex-m8-final-targeted-cache`: passed with 19 tests.
    - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-final-cov-basetemp -o cache_dir=.tmp\codex-m8-final-cov-cache`: passed with total coverage 100.00%.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 217 files already formatted.
    - `python -m pytest tests/unit/test_coverage_policy.py tests/unit/test_validators.py tests/unit/test_typing_policy.py -p no:schemathesis --basetemp .tmp\codex-m8-final-combined-basetemp -o cache_dir=.tmp\codex-m8-final-combined-cache`: passed with 20 tests.
    - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-final-cov2-basetemp -o cache_dir=.tmp\codex-m8-final-cov2-cache`: passed with total coverage 100.00%.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m8-final-full-basetemp -o cache_dir=.tmp\codex-m8-final-full-cache`: passed with 767 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
- M3 first strict mypy slice on 2026-05-05:
  - Closed local audit item partially: `src.quality.validators.*` now has scoped `disallow_untyped_defs = true`; global mypy `disallow_untyped_defs` remains `false`.
  - Red/green verification: `python -m pytest tests/unit/test_typing_policy.py -p no:schemathesis --basetemp .tmp\codex-m3-typing-red-basetemp -o cache_dir=.tmp\codex-m3-typing-red-cache` failed before the scoped override, then passed after implementation.
  - Mypy verification:
    - `python -m mypy src\quality\validators\schema_validator.py --config-file pyproject.toml --disallow-untyped-defs --follow-imports=skip --no-incremental --show-error-codes`: failed before implementation with one missing return type annotation.
    - `python -m mypy src\quality\validators --config-file pyproject.toml --follow-imports=skip --no-incremental --show-error-codes`: passed after adding the scoped override and annotations. The targeted run still prints the existing unused `src.processing.flink_jobs.*` override warning because that module is outside the checked slice.
  - Targeted verification:
    - `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_validators.py -p no:schemathesis --basetemp .tmp\codex-m3-final-targeted-basetemp -o cache_dir=.tmp\codex-m3-final-targeted-cache`: passed with 13 tests.
    - `python -m ruff check src\quality\validators\schema_validator.py tests\unit\test_typing_policy.py`: passed.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 216 files already formatted.
    - `python -m mypy src\quality\validators --config-file pyproject.toml --follow-imports=skip --no-incremental --show-error-codes`: passed. The targeted run still prints the existing unused `src.processing.flink_jobs.*` override warning because that module is outside the checked slice.
    - `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_validators.py tests/unit/test_staging_rollback.py tests/unit/test_security_workflow.py tests/unit/test_security_tooling_policy.py tests/unit/test_bandit_diff.py -p no:schemathesis --basetemp .tmp\codex-m3-final-combined-basetemp -o cache_dir=.tmp\codex-m3-final-combined-cache`: passed with 21 tests.
    - `git diff --check`: passed.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m3-final-full-basetemp -o cache_dir=.tmp\codex-m3-final-full-cache`: passed with 760 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`: passed with no new findings.
- M7 staging rollback safety on 2026-05-05:
  - Closed local audit item: `scripts/k8s_staging_up.sh` now runs `helm upgrade --install` with `--atomic` and includes `helm history "$RELEASE_NAME" --namespace "$NAMESPACE"` in failure diagnostics.
  - Red/green verification: `python -m pytest tests/unit/test_staging_rollback.py -p no:schemathesis --basetemp .tmp\codex-m7-rollback-red-basetemp -o cache_dir=.tmp\codex-m7-rollback-red-cache` failed before the script change, then the targeted test passed after implementation.
  - Targeted verification:
    - `python -m pytest tests/unit/test_staging_rollback.py -p no:schemathesis --basetemp .tmp\codex-m7-rollback-targeted-basetemp -o cache_dir=.tmp\codex-m7-rollback-targeted-cache`: passed with 1 test.
    - `python -m ruff check tests/unit/test_staging_rollback.py`: passed.
    - `bash -n scripts/k8s_staging_up.sh`: passed.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 215 files already formatted.
    - `python -m pytest tests/unit/test_staging_rollback.py tests/unit/test_security_workflow.py tests/unit/test_security_tooling_policy.py tests/unit/test_bandit_diff.py -p no:schemathesis --basetemp .tmp\codex-m7-final-targeted-basetemp -o cache_dir=.tmp\codex-m7-final-targeted-cache`: passed with 8 tests.
    - `bash -n scripts/k8s_staging_up.sh`: passed.
    - `python -c "import pathlib, yaml; [yaml.safe_load(path.read_text(encoding='utf-8')) for path in pathlib.Path('.github/workflows').glob('*.yml')]; print('workflow yaml ok')"`: passed.
    - `git diff --check`: passed.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m7-final-full-basetemp -o cache_dir=.tmp\codex-m7-final-full-cache`: passed with 759 passed, 4 skipped, and 105 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`: passed with no new findings.
- `git status --short --branch -- docs/operations/guarded-autopilot-scheduler-opt-in-boundary.md AGENT_STATE.md BACKLOG.md`: during task 17 final check, expected changes are `AGENT_STATE.md`, `BACKLOG.md`, and `docs/operations/guarded-autopilot-scheduler-opt-in-boundary.md`.
- `git rev-parse --short HEAD`: `7900754`.
- `Get-Command pi`: available.
- `Get-Command codex`: available.
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`: passed during task 17 verification; dry-run reported the PAUSE and BLOCKED protocols OK, noted `.autopilot/allowed-paths.txt` is required before execution, confirmed `pi` and `codex` are available, and ran `git status --short -uno` plus `git diff --check`.
- `powershell -ExecutionPolicy Bypass -File scripts/install-autopilot-task.ps1`: preview passed during task 16; scheduler was not installed.
- `git diff --check`: passed during task 17 verification.
- `python -m pytest tests/unit -p no:schemathesis`: passed with 454 tests.
- `python -m ruff check src/ tests/`: passed.
- `python -m ruff format --check src/ tests/`: passed.
- Historical only; do not repeat on this Windows workstation: `python -m pytest -p no:schemathesis` passed with 753 passed, 4 skipped, and 104 warnings after Docker Desktop was started.
- Current Windows broad-test pattern: `$env:SKIP_DOCKER_TESTS='1'; python -m pytest -p no:schemathesis` passed with 729 passed, 28 skipped, and 104 warnings before Docker was available.
- Mac Docker smoke on iMac `julia@192.168.1.133` at checkout HEAD `ffeb423`:
  - `docker build -f Dockerfile.api -t agentflow-api:mac-docker-smoke-ffeb423 .`: passed.
  - `docker compose -p agentflow-e2e-mac -f docker-compose.e2e.yml up -d --build --wait agentflow-api`: passed; Redis/Postgres/Kafka/API containers reached Docker `Healthy`.
  - `curl http://127.0.0.1:8000/v1/health`: returned JSON with `kafka:healthy` and `duckdb_pool:healthy`; aggregate `status` stayed `unhealthy` because Flink/Iceberg/freshness/quality are outside the e2e compose stack.
  - Cleanup verified with `docker compose ... down -v`; only pre-existing `hq-demo` kind containers remained.
- Mac pytest-based compose smoke on iMac `julia@192.168.1.133` after commit `677de80`:
  - `AGENTFLOW_E2E_MODE=compose AGENTFLOW_E2E_TIMEOUT=180 .venv-mac-docker/bin/python -m pytest tests/e2e/test_smoke.py::test_webhook_test_endpoint_delivers_callback -v --tb=short -p no:schemathesis --basetemp .tmp/mac-e2e-webhook-basetemp -o cache_dir=.tmp/mac-e2e-webhook-cache`: passed with `1 passed in 108.91s`.
  - `AGENTFLOW_E2E_MODE=compose AGENTFLOW_E2E_TIMEOUT=180 .venv-mac-docker/bin/python -m pytest tests/e2e/test_smoke.py -v --tb=short -p no:schemathesis --basetemp .tmp/mac-e2e-smoke-basetemp -o cache_dir=.tmp/mac-e2e-smoke-cache`: passed with `10 passed in 121.10s`.
  - Cleanup verified with `docker ps --all`; only pre-existing `hq-demo` kind containers remained.
- Standalone lint/typecheck/build gates: not run separately; no frontend source was changed.
- Local verification matrix: documented in `docs/operations/local-verification-matrix.md`.
- `cd sdk-ts; npm run typecheck`: passed.
- `cd sdk-ts; npm run test:unit`: passed with 46 tests.
- `cd sdk-ts; npm run build`: passed.

## Runtime Gaps

- Integration, staging, load, publish, and Terraform workflows depend on Docker, Kubernetes, cloud credentials, external services, or GitHub secrets and are forbidden for autopilot by default.
- On this Windows workstation, Docker Desktop, Docker compose/build, kind, Helm live validation, chaos tests, and Docker-dependent full pytest are forbidden local gates because Docker can hang processes. Use the Mac runner or CI for that evidence.
- The iMac host can run Docker build and compose smoke checks via SSH and now has a repo-local Python 3.11 verification environment at `/Users/julia/agentflow-docker-check/.venv-mac-docker`, but it is not registered as a GitHub Actions self-hosted runner.
- The runner cannot sandbox `pi` or `codex` to path-level writes before execution; it enforces allowed paths after execution and blocks commits on violations.
- Scheduler is intentionally not enabled by setup.

## Safe Scope

- Documentation under `docs/` and root markdown files.
- Unit/property tests that do not require Docker, cloud credentials, or live services.
- Broad local pytest with `SKIP_DOCKER_TESTS=1`.
- Local-only scripts that do not deploy, publish, rotate secrets, or delete project data.
- Small source changes when the required verification can run locally.

## Forbidden Scope

- `.github/workflows/*publish*`, `.github/workflows/terraform-apply.yml`, deployment workflows, and release publishing.
- Starting Docker Desktop or running Docker-backed gates on this Windows workstation.
- `deploy/`, production `docker-compose` flows, `helm/`, `k8s/`, and `infrastructure/terraform/` unless the user explicitly assigns a bounded non-deploy documentation task.
- Secret files, `.env*`, API keys, tokens, recovery codes, cloud accounts, npm/PyPI publishing, and paid external API calls.
- Runtime databases, warehouses, logs, and generated artifacts.

## Next Step

Backlog tasks 0 through 17 and 23 through 24 are complete. Task 18 AWS/Terraform is out of scope by operator budget/payment constraint, not an active blocker. Tasks 19 through 22 remain blocked on real external inputs: production CDC owner decisions, real PMF/pricing/customer evidence, approved production-hardware benchmark evidence, and an external pen-test attestation. The 2026-05-30 Codex audit items from `audit_codex_30_05_26.md` and the follow-up local docs/SDK/security boundary items are locally closed through `0759fc6`. On 2026-05-30 the M-C4 hashed-key guidance was promoted from docs-only to a runtime `hashed_key_count_exceeds_guidance` warning in `AuthManager.load()` (HEAD `e444ecf`, six main workflows green). The full hashed-key-lookup rewrite (bcrypt hash-format swap) stays deferred. No additional safe audit-driven code item is queued.

The 2026-05-30 operator instruction to run Docker locally on this Windows workstation was issued and then explicitly reversed within the same session ("do not run Docker here, it kills processes; run on the Mac"). A Docker Desktop start + `docker build` were begun and then fully stopped: the background build and monitor were killed, Docker Desktop / engine / `docker-agent` / `docker-sandbox` processes were force-stopped, and `wsl --shutdown` released the WSL2 VM. No containers or compose stacks were started, no image was produced, and the worktree stayed clean. The no-Docker-on-Windows policy stands: Docker-heavy verification is Mac/CI only; the machine is low-powered and Docker hangs processes here.

On 2026-05-30 the strict-typing cadence was extended autonomously across two more commits: `src.serving.api.auth.*` (`f977317`) and `src.quality.monitors.*` (`3e7434b`) are now strict mypy slices alongside `src.quality.validators.*`. Typing the monitors slice surfaced and fixed a real latent tombstone bug in `FreshnessMonitor._process_message`. All landed with six main workflows green (one Load Test re-run for runner variance). `mypy src` is clean on 99 files.

**Standing autonomous mandate (operator-granted 2026-05-30):** the agent owns all tactical and external/strategic decisions, keeps finishing safe local work without asking "what next", and stops only at a named hard boundary. External data / AWS / paid services are out of scope (no card/budget), not a deficiency. Local commits and ordinary `git push origin main` are authorized after clean status + `git diff --check`. The canonical uninterrupted-session starter, including the copy-paste kickoff prompt, the work-selection priority order, and the verification discipline, is `next-session-autonomous-local-plan.md` — start there.

Strict mypy slices now cover `src.quality.validators.*`, `src.serving.api.auth.*`, `src.quality.monitors.*`, `src.serving.semantic_layer.*`, `src.serving.backends.*`, `src.orchestration.dags.*` (HEAD `80316fb`; surfaced + fixed the DuckDB `fetchone()` None-indexing bug), `src.processing.event_replayer` (HEAD `8a50ab6`), `src.processing.local_pipeline` (HEAD `98a9ed5`), and `src.processing.outbox` (HEAD `0953fcc`; `_connection` property guards use-after-close). All of `src/processing` except the PR-#23-gated `flink_jobs` is now strict-typed, plus six `src/serving/api` slices: `src.serving.api.middleware.*` (HEAD `4ad01fd`), `src.serving.api.routers.deadletter` (HEAD `e92a6eb`), `src.serving.api.routers.webhooks` (code HEAD `45d3fc5`), `src.serving.api.routers.alerts` (code HEAD `5f61fd3`), `src.serving.api.routers.contracts` (code HEAD `84c63dc`), and `src.serving.api.routers.agent_query` (code HEAD `0cdac06`). Measured after the agent-query slice, the remaining untyped-def population is 43: `src/serving/api` has 30 remaining (largest clusters: `routers/admin.py`=12, `main.py`=6, then a long tail of 1-2 per file) plus `src/processing/flink_jobs` has 13 (gated by its own override + PR #23 / Docker). The `src/serving/api` remainder is incremental, not load-bearing; pick it up only as bounded, individually-verified slices (one coherent module/package at a time, typing-policy assertion + full `mypy src` + broad unit + six green workflows each).

Everything else is gated: H-C2 (live ClickHouse), M-C2/M-C3 (upstream PR #23), M-C4 full rewrite (hash-format swap), build-smoke required-check (needs a workflow always-run change before the branch-protection boundary), Tier B A04/A05, and tasks 19-22 (external evidence). Do not convert blocked external gates into completed work without real operator-provided evidence, and do not churn handoff docs only to bump HEAD/timestamps.
