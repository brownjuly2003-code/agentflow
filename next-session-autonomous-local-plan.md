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
4. **Strict-typing cadence** (incremental, not load-bearing) — promote one more
   module to a strict mypy slice (`disallow_untyped_defs = true`). Done so far:
   `src.quality.validators.*`, `src.ingestion.schemas.events`,
   `src.ingestion.producers.event_producer`, `src.serving.api.auth.*`,
   `src.quality.monitors.*`, `src.serving.semantic_layer.*`,
   `src.serving.backends.*`, `src.orchestration.dags.*`,
   `src.processing.{event_replayer,local_pipeline,outbox}`,
   `src.serving.api.middleware.*`, `src.serving.api.routers.deadletter`, and
   `src.serving.api.routers.{webhooks,alerts,contracts,agent_query,batch,search}`,
   `src.serving.api.rate_limiter`, `src.serving.api.security`,
   `src.serving.api.versioning`, `src.serving.api.analytics`,
   `src.serving.api.routers.lineage`, `src.serving.api.routers.slo`, and
   `src.serving.api.routers.stream`, `src.serving.api.routers.admin_ui`, and
   `src.serving.api.webhook_dispatcher`.
   Remaining measured candidates after the webhook dispatcher slice: 20
   untyped functions across 3 files in `src/serving/api`
   (`routers/admin.py`=12, `main.py`=6, and `alerts/dispatcher.py`=2). These
   three API-side files all require a focused Claude second opinion before
   coding. The attempted `alerts/dispatcher.py` second-opinion call failed with
   a Claude socket close; the exact prompt is preserved in
   `second-opinion-alerts-dispatcher.md`, and no code was changed. Do not retry
   the same alerts prompt unchanged without new evidence that Claude is
   available. `src/processing/flink_jobs` remains gated by PR #23 / Docker.
   The latest completed non-API slices are `src.ingestion.schemas.events`
   (`fc01360`, all six workflows green) and
   `src.ingestion.producers.event_producer` (`890b30f`; push Load Test had a
   p99-only variance failure, and same-SHA reruns `26727841007` /
   `26727894286` passed); do not repeat them.
   Typing a module often surfaces real latent bugs — fix them, don't suppress.
5. **Coverage cadence** — add/raise a per-module 90% coverage gate where a
   module is under-tested. Latest completed gate: `5fecb1b` pins
   `src.ingestion.producers.event_producer` at 90% minimum module coverage
   (local baseline 96.39%, all six workflows green).

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
