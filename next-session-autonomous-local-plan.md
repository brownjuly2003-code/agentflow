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
   is the sole relaxation (PyFlink, gated on PR #23) and the only typing work
   that remains. Do **not** re-add per-module `disallow_untyped_defs = true`
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
   FastAPI route slices. `src/processing/flink_jobs` remains gated by PR #23 /
   Docker.
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
   58%→92% via `tests/unit/test_outbox_processor.py`, `coverage run` form). The
   last mutmut target without a unit-only gate is
   `src.serving.semantic_layer.query_engine` (imports duckdb → `coverage run`
   gate form; the query orchestration surface). Pick a new under-tested module
   only on real evidence (mutmut/security-critical qualifies; arbitrary modules
   do not).

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

- **H-C2** full sqlglot ClickHouse transpile — needs live ClickHouse coverage
  (Mac/Docker).
- **M-C2 / M-C3** Flink hot-path — gated on upstream PR #23 (no Flink 2.x Kafka
  connector JAR yet).
- **M-C4** full hashed-key-lookup rewrite — needs the bcrypt→argon2id
  hash-format swap (the soft-limit warning is already shipped).
- **build-smoke → required check** — needs a workflow change first (it is
  path-filtered, so a bare promotion hangs every non-Docker PR like the
  `contract` Lessons 1/4 trap); then a branch-protection change (named
  boundary).
- **Tier B A04/A05** + **tasks 19-22** — production CDC owners, real
  PMF/customer evidence, production-hardware benchmark, external pen-test:
  external evidence only.
- **v1.5.0** — cut only when real feature changes accumulate (current
  `[Unreleased]` is hardening + deps); tag publish is a named boundary.

## Done When

The session ends with either a verified scoped commit pushed to `origin/main`
with six green workflows, or a clean worktree plus a durable note that no safe
local candidate remains without new evidence or an explicitly named boundary.
