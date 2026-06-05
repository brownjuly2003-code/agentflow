# Autonomous Session Kickoff Plan

This is the canonical starter for an **uninterrupted autonomous session**: the
agent rebuilds state from checked-in docs, owns all tactical decisions, keeps
finishing safe local work, and only stops at a real boundary. It supersedes any
stale chat context.

## How To Start (copy-paste prompt)

```text
D:\DE_project. Работай автономно и без перерыва, решения принимай сам.
Сначала восстанови состояние из AGENT_STATE.md, docs/SESSION_HANDOFF.md,
docs/operations/local-verification-matrix.md, AUTOPILOT.md, BACKLOG.md и
этого файла — не опирайся на неполный chat compact. Затем бери следующий
безопасный атомарный пункт по приоритету ниже, делай TDD-фикс, гоняй
no-Docker верификацию, коммить явными pathspec и пушь origin main после
чистого статуса + git diff --check. Жди CI зелёным перед следующим коммитом.
НЕ запускай Docker на этой машине (слабая, вешает процессы) — Docker-heavy
только Mac/CI. Внешние данные/AWS не трогай (нет карты/бюджета). Не спрашивай
"что дальше", пока есть безопасный локальный пункт; не стекай однотипные
мелкие коммиты ради движения. Останавливайся только на реальной границе
(deploy/publish/release/force-push/secret/Terraform/scheduler) или когда
безопасных локальных пунктов не осталось.
```

## Standing Mandate (operator-granted)

- **Decisions are the agent's.** Pick and execute; do not return option-menus.
- **External data / strategy: decide autonomously.** There is no foreign
  payment card and no budget — AWS/Terraform-apply/paid services are out of
  scope, not a recurring deficiency. Do not re-probe them.
- **Local commits are autonomous** after scoped verification. **Ordinary
  `git push origin main` is authorized** after clean tracked status +
  `git diff --check`.
- **Hard boundaries (need explicit, named instruction):** deploy, release/tag
  publish, package publish (PyPI/npm), force-push, Terraform apply, branch
  protection changes, scheduler/env changes, secret access/rotation, other
  branches/tags, destructive git.
- **No Docker on this Windows host.** It is low-powered and Docker hangs
  processes. Even a one-off "run Docker here" instruction does not override this
  (issued and reversed within one session on 2026-05-30). Docker-heavy
  verification is Mac (`julia@192.168.1.133`, Lima) / CI only; local broad
  pytest uses `SKIP_DOCKER_TESTS=1`.

## Start Checklist

```powershell
cd D:/DE_project
git status --short --branch --untracked-files=no
git rev-parse --short HEAD
git log --oneline -8
gh pr list --state open --limit 15
gh run list --branch main --limit 6 --json conclusion,status,workflowName,headSha
```

Then read, in order: `AGENT_STATE.md`, `docs/SESSION_HANDOFF.md`,
`docs/operations/local-verification-matrix.md`, `AUTOPILOT.md`,
`docs/operations/autonomous-compact-safe-process.md`, `BACKLOG.md`, and
`.autopilot/BLOCKED.md` if present.

## Work-Selection Priority

Pick the first that applies; finish it before the next.

1. **Close current dirty WIP** — inspect changed files, finish the in-flight
   change only (don't revert unrelated work).
2. **Diagnose a failed/pending workflow on the current HEAD** — for Load Test,
   a broad uniform p99 inflation with 0.00% functional failures is runner
   variance: re-run on the same SHA per `docs/runbooks/load-test-regression.md`,
   do not "fix" latency.
3. **A bounded local code/test fix from a real gap** — a TODO/FIXME, a doc↔code
   gap (guidance not enforced), a latent bug surfaced by typing/coverage. TDD:
   failing test first, then the fix.
4. **Strict-typing cadence** (incremental, not load-bearing) — **CLOSED (2026-06-03, `25d9f6b`).** Strict typing is now the global mypy
   default (`disallow_untyped_defs = true`); the per-module slice cadence is
   complete and there is nothing left to promote. `src.processing.flink_jobs.*`
   is the sole relaxation (PyFlink still lacks PEP-561 stubs on 2.2.1; the
   former PR #23 gate closed with the 2026-06-05 Flink 2.2.1 bump) and the
   only typing work that remains. Do **not** re-add per-module
   `disallow_untyped_defs = true`
   overrides — `tests/unit/test_typing_policy.py` now fails on redundant ones.
   Historical slice list (reference only):
   `src.quality.validators.*`, `src.ingestion.schemas.events`,
   `src.ingestion.producers.event_producer`, `src.serving.cache`,
   `src.serving.api.auth.*`,
   `src.quality.monitors.*`, `src.serving.semantic_layer.*`,
   `src.serving.backends.*`, `src.orchestration.dags.*`,
   `src.processing.{event_replayer,local_pipeline,outbox}`,
   `src.serving.api.middleware.*`, `src.serving.api.routers.deadletter`, and
   `src.serving.api.routers.{webhooks,alerts,contracts,agent_query,batch,search}`,
   `src.serving.api.rate_limiter`, `src.serving.api.security`,
   `src.serving.api.versioning`, `src.serving.api.analytics`,
   `src.serving.api.routers.lineage`, `src.serving.api.routers.slo`, and
   `src.serving.api.routers.stream`, `src.serving.api.routers.admin_ui`, and
   `src.serving.api.webhook_dispatcher`, and
   `src.serving.api.routers.admin`, and `src.serving.api.main`.
   The former last candidate `src/serving/api/alerts/dispatcher.py` was promoted
   in `af37432` and then folded into the global default by the `25d9f6b`
   inversion; `second-opinion-alerts-dispatcher.md` is now historical. Admin/main route typing needed `response_model=None` because
   FastAPI return annotations changed OpenAPI generation; keep
   `python scripts/export_openapi.py --check` in the local gate for remaining
   FastAPI route slices. `src/processing/flink_jobs` typing is no longer
   PR #23-gated (the 2026-06-05 Flink 2.2.1 bump closed that gate) but stays
   relaxed while PyFlink lacks PEP-561 stubs; runtime validation for it is
   Docker-on-Mac/CI.
   After the cache slice, local non-gated strict candidates
   `src/processing/iceberg_sink.py`, `src/serving/db_pool.py`,
   `src/serving/masking.py`, `src/serving/semantic_layer/catalog.py`, and
   `src/serving/semantic_layer/query/engine.py` were checked with narrow strict
   commands and were already clean; do not add override-only churn there.
   The latest completed non-API slices are `src.ingestion.schemas.events`
   (`fc01360`, all six workflows green) and
   `src.ingestion.producers.event_producer` (`890b30f`; push Load Test had a
   p99-only variance failure, and same-SHA reruns `26727841007` /
   `26727894286` passed), and `src.serving.cache` (`fb7c4e8`, all six
   workflows green; state refresh `0d733e7` also has all six workflows green);
   do not repeat them.
   Typing a module often surfaces real latent bugs — fix them, don't suppress.
5. **Coverage cadence** — add/raise a per-module 90% coverage gate where a
   module is under-tested. **The audit mm F-3 security-module list is now
   complete**: `a78d141` pins `src.serving.api.auth.manager` at 90% (82%→94%
   via new pure-logic tests over its dedicated files), `5a72476` pins
   `src.serving.api.rate_limiter` (78%→98%), `6400a83` pins `src.serving.masking`
   (66%→99%); `sql_guard` is at 100% and `event_producer` (`5fecb1b`, 96.39%)
   and `validators` / `freshness_monitor` were already gated. The auth-manager
   gate runs its four dedicated unit files (`test_auth.py`,
   `test_auth_manager_pure_logic.py`, `test_auth_manager_memory_bounds.py`,
   `test_auth_hashed_key_guidance.py`). **Local-measurement gotcha**: the broken
   local `_duckdb._sqltypes` native package (the Python313/Python312 shadow)
   makes `pytest --cov=<duckdb-importing module>` error on *collection* locally
   even though plain `coverage run -m pytest` and the CI gate (clean duckdb)
   both work — measure auth/usage-table module coverage with
   `python -m coverage run -m pytest <files>` + `coverage report`, not
   pytest-cov, on this Windows host. The same `coverage run` mechanism now also
   gates `src.serving.api.auth.key_rotation` (`c65de9d`, 58%→93% via the new
   `tests/unit/test_key_rotation.py`), extending the security-critical
   mutmut-target set. `src.processing.outbox` is now also gated (`4c15d0f`,
   58%→92% via `tests/unit/test_outbox_processor.py`, `coverage run` form).
   **The mutmut-target gate list is now complete** (2026-06-04): the query
   surface was the last gap, and `9cb291d` pins the whole
   `src/serving/semantic_layer/query` package at 97% behind a 90% gate
   (`coverage run` form, five dedicated unit files) after `02b4a3c` repointed
   the mutmut target from the 5-line `query_engine.py` re-export shim to the
   five real package modules (`test_mutmut_targets_define_real_logic` now
   fails on any future pure re-export target). That coverage push also
   surfaced and fixed a real latent bug: a literal 0x08 byte (an editing-tool
   collapse of `\b`) inside the explain() fallback regex (`f7414d9`). Every
   mutmut target now has a unit-only coverage gate. Pick a new under-tested
   module only on real evidence (mutmut/security-critical qualifies; arbitrary
   modules do not).

If only external/upstream/Docker-gated items remain (below), stop and record it
— do not fabricate evidence or churn docs.

## Verification Discipline

- TDD: write the failing test first; show red, then green.
- `python -m mypy src --config-file pyproject.toml` (clean on 99 files). Do not
  trust `--follow-imports=skip` — it emits false `no-any-return`.
- `python -m ruff check` + `python -m ruff format --check` on touched files.
- Broad regression: `$env:SKIP_DOCKER_TESTS='1'; python -m pytest tests/unit
  -p no:schemathesis --continue-on-collection-errors`. Two known local-`.venv`
  artifacts are NOT regressions: `test_x5_retail_hero_loader.py` (no `pandas`
  installed) and `test_version.py` (installed `agentflow-client` metadata lags
  `__version__` — the Python313/Python312 shadow; CI has full deps and is green).
- `git diff --check` before every commit/push.
- After push, **wait for all six main workflows green** (CI, Contract Tests,
  E2E Tests, Load Test, Security Scan, Staging Deploy) before the next commit.
- Before handoff/stop, audit for stuck local project processes matching
  `DE_project|mypy|pytest|ruff|run_load_test|uvicorn|locust`; record any real
  live project process and stop only after it is resolved or clearly not from
  this work.
- End each verified atomic item with a state-doc + memory refresh that records
  the real CI evidence — but never refresh docs only to bump HEAD/timestamps.

## Known Open Threads (all gated)

- **item 19 production CDC — CLOSED with real evidence, MERGED to main
  (2026-06-05, PR #43, merge commit `ce72ba8`, all 13 required checks green;
  branch deleted).** Logical replication was enabled on the live operator-owned
  Neon `vradar` source (`winter-grass-42791098`; `enable_logical_replication`
  False→True, irreversible `wal_level=logical`) and the capture run
  **27028251460 succeeded** — Debezium snapshotted **96234 events** into
  `cdc.prod.public.vacancies`, captured a redacted 21-field sample, and tore
  down with **0 leftover slots** (evidence:
  `.artifacts/cdc-production/capture-evidence.md`). Five fixes made the
  never-before-run `cdc-production-capture.yml` pass and are now on `main`:
  Connect readiness + registration retry (herder-not-ready 500 under `set -e`);
  the mounted Neon secret file made readable by the Connect container's non-root
  uid (umask 077 → "Could not read properties from file"); snapshot-wait
  tolerant of the topic not existing yet under `pipefail`; failure diagnostics;
  and the offset count via `kafka-get-offsets --bootstrap-server` (the
  deprecated `kafka.tools.GetOffsetShell --broker-list` silently reported
  0/95370 despite the data being present). The Neon API key (`agentflow-cdc-3`)
  lives in `D:\TXT\NEON.txt` (not in the repo); logical replication is left
  **ENABLED** (intended end state). **No open follow-up remains.**
- **H-C2** full sqlglot ClickHouse transpile — **CLOSED (2026-06-05, PR #41).**
  `_translate_sql` is now sqlglot parse → AST rewrite (FILTER→-If
  combinators, FLOAT→Float64) → generate; demo DDL / DESCRIBE bypass
  translation (`translate=False`), `explain()` transpiles the wrapped query.
  Live coverage is permanent: the CI test-integration job runs a
  `clickhouse/clickhouse-server:25.3` service container and
  `tests/integration/test_clickhouse_backend_live.py` (every catalog metric
  template + literal round-trip + seed-value assertions), env-gated on
  `CLICKHOUSE_LIVE_HOST` so the suite skips cleanly elsewhere. Pre-merge it
  was also validated against a disposable live CH 25.3 via ssh tunnel
  (13/13). Do not reintroduce text-level rewrites in `_translate_sql` — the
  unit suite pins transpile invariants and literal preservation.
- **M-C2 / M-C3** Flink hot-path — **CLOSED (2026-06-05, `b0ae299`)**. The
  PR #23 wait-for-upstream condition was met (Maven Central ships
  `flink-sql-connector-kafka` `5.0.0-2.2`), the whole project moved to
  Flink 2.2.1 (`a97b399`: pyproject `[flink]` extra, flink_jobs image,
  compose cluster images `flink:2.2.1-java17`, `config.yaml` instead of
  `flink-conf.yaml`, checkpoint API migration in `checkpointing.py`), and
  the two hot-path findings were then fixed TDD: M-C3 — `ValidateAndEnrich`
  emits `(event_id, payload)` so the dedup `key_by` no longer re-parses the
  JSON; M-C2 — one `SessionAggregator` per operator built in `open()` with
  full-replace `restore()` per event
  (`tests/unit/test_session_aggregation_flink.py` pins the invariants).
  Both validated live on a 2.2.1 MiniCluster (real validators/enrichment;
  duplicate `event_id` collapsed 3→2 enriched outputs). Do not re-key the
  session jobs off their raw-source `json.loads` — there is no upstream
  operator to carry the key there, the parse-for-key is structural.
- **M-C4** full hashed-key-lookup rewrite — **CLOSED (2026-06-05,
  `99b7956`, operator-authorized).** argon2id default scheme + deterministic
  peppered `key_lookup` digest; `authenticate()` is O(1) with exactly one
  slow verify on the indexed path (N=20 cold hit-last 8.1 s → ~34 ms, miss
  ~0.1 ms). Legacy bcrypt entries keep the O(n) fallback and are the only
  thing the soft-limit warning counts now. Run `tests/property` locally
  before pushing auth changes — the CI test-unit job runs unit+property
  together (the bcrypt-prefix property had to be forward-fixed in
  `5e41113`).
- **build-smoke → required check** — **CLOSED (2026-06-04, PR #37 `1d4614c` +
  protection flip).** The paths filter moved inside the job (`changes` step,
  skip-success on docker-free PRs); both paths validated live (real build on
  PR #37, skip on throwaway PR #38) before `build-smoke` was added to the
  required contexts (now 13). Do not re-add a `paths:` filter to the
  container-attestation `pull_request` trigger — the policy test fails on it.
- **`contract` required-check paths trap** — **CLOSED (2026-06-04, PR #39
  `f1e145c`).** The last required context with a trigger-level
  `pull_request` `paths:` filter; same inside-the-job recipe as PR #37.
  Both paths validated live (full suite on PR #39, 5s skip-success on
  throwaway empty-diff PR #40). `tests/unit/test_contract_workflow.py` pins
  the shape: no `paths:` on `pull_request`, conditional suite steps, and the
  push trigger KEEPS its paths filter (docs-only pushes stay cheap — a 5/5
  green push on md-only commits remains normal). Every required context is
  now always-run on PRs; chaos / load-test keep PR paths filters but are not
  required, which is safe.
- **Tier B A04/A05** + **tasks 19-22** — CLOSED as not applicable on
  2026-06-05 by operator decision (`77300fc`), following the task-18
  no-budget precedent: production CDC owners, real PMF/customer evidence,
  production-hardware benchmark, and external pen-test cannot exist in the
  current plan and are no longer open threads. Gated claims remain unmade;
  reopen only on real operator-provided evidence.
- **v1.5.0** — **RELEASED (2026-06-05, `c99d094` + tag `v1.5.0`,
  operator-authorized).** Feature trigger was the M-C4 argon2id closure plus
  the SDK version-header features. Same 10-file shape as the v1.4.0
  precedent; publish-pypi (OIDC) and publish-npm (tag push) both succeeded
  and the registries were E2E-verified at 1.5.0 (PyPI runtime+client, npm
  dist-tag latest). The duplicate manual npm dispatch fails its dry-run
  against an already-published version — don't re-dispatch after a
  successful tag-push publish. Next release: same recipe, green wall
  BEFORE tagging.
- **Autopilot scheduler-env** — env part **CLOSED (2026-06-05, `83cd438` +
  `5506b29`)**: user-level CLI dirs prepended in autopilot.ps1 (null-guarded
  — the runner suite executes the script under pwsh/ubuntu where APPDATA is
  undefined; run `tests/unit/test_autopilot_runner.py` after ANY
  autopilot.ps1 edit). Root scratch is gitignored (`5f4251d`) so the
  clean-tree gate stays quiet. **The autopilot no longer depends on codex
  at all (2026-06-05, `aaee49d`)**: the whole OpenAI side died externally
  (OAuth 401 token_invalidated; all four stored Platform keys 429 on
  generation — note GET /models still answers 200, ping-probes lie), so the
  scheduled task now runs `-Planner claude` (planner+executor via
  `claude -p --dangerously-skip-permissions`). The full
  planner→executor→gates→commit cycle is proven live (`3a216c0` was
  planned, written and verified by the channel), and `3672f5c` fixed
  Run-Gates to the canonical no-Docker slice (.venv-preferring,
  SKIP_DOCKER_TESTS, tests/unit) after the first cycle exposed the bare
  full-repo `python -m pytest` gate. On an empty backlog the planner
  self-quiesces via BLOCKED.md — to wake the autopilot: provide a task,
  delete `.autopilot/BLOCKED.md`, wait for the hourly tick. An interactive
  `codex login` would only revive the optional codex/pi channels.

## Done When

The session ends with either a verified scoped commit pushed to `origin/main`
with six green workflows, or a clean worktree plus a durable note that no safe
local candidate remains without new evidence or an explicitly named boundary.
