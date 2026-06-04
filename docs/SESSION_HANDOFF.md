# AgentFlow — Session Handoff

**Last updated:** 2026-06-04 (coverage cadence COMPLETE: every mutmut target
unit-gated; query package gate + 0x08 regex fix + mutmut shim repoint;
Dependabot wave 4 merged; **audit mm F-5 closed** — bandit baseline emptied)
**Verified code/state HEAD before this refresh:** `b6c5fb4` on `main` (even with
`origin/main`). Six main workflows green on `b6c5fb4` (**F-5**: the baseline's
single accepted B310 finding moved to an inline
`# nosec B310 - <reason>` at the `urlopen` call in `clickhouse_backend.py`,
matching the file's B608 convention; `.bandit-baseline.json` is now empty and
a new policy test `test_bandit_baseline_carries_no_suppressed_findings` keeps
it that way — this also retires the line-keyed-baseline drift trap where any
line shift above the baselined call failed Security Scan on unrelated edits.
Future accepted findings go inline with a reason, never into the baseline).
Session 2026-06-04 stack on top of the prior `5936f8d` state:
`ccbf230` (F-6 handoff refresh), `6400a83` + `242fbdf` (PII masking 66%→99% +
90% gate), `5a72476` + `d191694` (rate limiter 78%→98% + gate), `a78d141` +
`e6914fa` + `6c779ee` (auth manager 82%→94% + gate; **gate gotcha:**
duckdb-importing modules need `coverage run` + `coverage report --include`,
not `pytest --cov` — pytest-cov instrumentation trips duckdb's lazy
`_duckdb._sqltypes` import at collection time on CI too), `c65de9d` +
`7d3a3c6` (key rotation 58%→93% + gate), `4c15d0f` + `8fa8a14` (outbox
58%→92% + gate), `02b4a3c` (**mutmut repoint**: `paths_to_mutate` pointed at
the 5-line `query_engine.py` re-export shim, so the query surface mutated
nothing; now targets the five real `query/` package modules, with an AST
policy test against future pure re-export targets), `f7414d9` (**real latent
bug**: a literal 0x08 byte — a collapsed `\b` escape — inside the `explain()`
fallback regex in `nl_queries.py` meant the regex never matched and
`tables_accessed` came back empty on the sqlglot-failure path; fixed + a
control-byte source guard), `9cb291d` (**query package coverage gate**: new
`tests/unit/test_query_package_logic.py` lifts the package 64%→97% behind a
90% CI gate over five dedicated unit files — **the coverage cadence is now
complete; every mutmut target has a unit-only gate**), Dependabot wave 4
merges `e342cb1`/#34, `223bd8a`/#33, `1ea1a77`/#35, `3cabb87`/#36 (pandas dev
`<4`), `a6886be`/#32 (schemathesis 4.21.0), `ef3d2a3`/#31
(attest-build-provenance v4; required unpinning
`test_container_attestation_workflow.py` from the exact action major — it now
matches by name prefix), and `9361360` (docs record). Six main workflows green
on `9cb291d`, `ef3d2a3`, and `9361360` (Contract Tests path-filtered on the
md-only docs commit, expected). Resolver smoke
(`pip install --dry-run -e ".[dev,cloud,contract]"`) green after the wave.
Earlier session 2026-06-03 stack on top of the prior `8032e24` state:
`09cc0ea` (api main strict slice state), `af37432` (alerts dispatcher strict
slice — closes the last src API untyped surface), `1480a32` (point mutmut
`paths_to_mutate` at the real `auth/manager.py` + `auth/key_rotation.py`; the
old `auth.py` path rotted and silently mutated nothing), `7eb8461` (**security
fix H-6**: NL→SQL guard now rejects DuckDB scan funcs — `read_csv`/`read_parquet`
parse to typed `exp.ReadCSV`/`exp.ReadParquet`, not `exp.Anonymous`, so they
bypassed the projection-position denylist; the check now inspects every
`exp.Func` node), `10c37a6` (changelog), `9f11417` (**F-3**: pin `sql_guard`
100% coverage behind a CI `--cov-fail-under=90` scoped gate), `475e984` +
`7f978a7` (docs/state + GitHub Releases v1.2–v1.4 record), `25d9f6b`
(**strict-typing cadence CLOSED** — invert `disallow_untyped_defs` to the global
default; `mypy src --disallow-untyped-defs` confirmed `flink_jobs` was the sole
untyped surface, so ~32 per-module overrides collapse to one relaxation),
`6ae7936` (pin `sql_guard` into mutmut targets + path-rot policy test
`test_mutmut_policy.py`), `f393cce` (state closeout), and `5936f8d` (**F-3 auth
half**: unit-cover the pure security logic in `auth/manager.py` —
`tenant_key_allowed_tables`, `validate_key_material`, `_legacy_env_keys`,
`_matches_key_material`; 21 new tests; CI now also carries a global
`--cov-fail-under=60` floor in `ci.yml`). Six main workflows green on
`5936f8d`. Earlier 2026-05-30 code stack:
`e444ecf` (M-C4 guidance enforcement), `f977317` (auth strict slice; Load Test
re-run once for variance), `3e7434b` (monitors strict slice + tombstone fix),
`30e20a7` (semantic-layer strict slice), `346bf64` (backends strict slice +
clickhouse CRLF→LF), `dd0a46d` (bandit baseline line-drift fix), `80316fb`
(orchestration.dags strict slice + DuckDB `fetchone()` None-safety fix),
`8a50ab6` (event_replayer strict slice), `98a9ed5` (local_pipeline strict
slice), `0953fcc` (outbox strict slice + `_connection` use-after-close guard),
`4ad01fd` (api request-middleware strict slice — first `src/serving/api` slice),
`e92a6eb` (dead-letter router strict slice — second `src/serving/api` slice),
`452d120` (webhooks router strict slice — third `src/serving/api` slice),
`45d3fc5` (generated OpenAPI refresh for the webhooks response schemas),
`5f61fd3` (alerts router strict slice + generated OpenAPI refresh),
`84c63dc` (contracts router strict slice + generated OpenAPI refresh),
`0cdac06` (agent query router strict slice), `0729fe5` (batch router strict
slice), `3d8c2e8` (search router strict slice), `b0c784f`
(rate-limiter strict slice), `44df329` (security helpers strict slice),
`eb5919e` (versioning helpers strict slice), `271b82c` (analytics
middleware strict slice), `d45ec9b` (lineage router strict slice),
`7a9379d` (SLO router strict slice), `3b2078a` (stream router strict
slice), `e53e0d3` (admin UI router strict slice), `66bc820`
(webhook dispatcher strict slice), `42c1f02` (alerts dispatcher second-opinion
prompt recorded after Claude socket close), `5fecb1b` (event producer scoped
coverage gate), `fc01360` (ingestion event schemas strict slice), `890b30f`
(event producer strict slice), `fb7c4e8` (serving cache strict slice), and
`0d733e7` (serving cache state refresh). Session 2026-06-01 then added
`da1bcfb` (Mac Docker restore state), `8e58854` (admin router strict slice),
and `28acdf9` (preserve admin OpenAPI response-model behavior after route
return annotations), and `8032e24` (API main strict slice + request.app state
lookup fix).
All of `src/processing` except the PR-#23-gated `flink_jobs` is now
strict-typed. Prior state-refresh HEAD `6866f68`; open-questions plan HEAD
`34d99da`.
**Branch state at refresh start:** `main...origin/main`; local `main` is even with `origin/main`.
**Tracked files at refresh start:** `918` via `git ls-files` (+3 test files
since `915`: `tests/unit/test_key_rotation.py`,
`tests/unit/test_outbox_processor.py`, `tests/unit/test_query_package_logic.py`).
**Latest local commits before this state refresh:**
- `9361360` docs: record query gate + 0x08 fix + mutmut repoint + Dependabot wave 4
- `ef3d2a3` chore(deps,ci): bump actions/attest-build-provenance from 2 to 4 (#31)
- `a6886be` chore(deps): bump schemathesis (#32)
- `3cabb87` chore(deps): update pandas requirement from <3,>=2.2 to >=2.2,<4 (#36)
- `1ea1a77` chore(deps,ci): bump aws-actions/configure-aws-credentials from 4 to 6 (#35)
- `223bd8a` chore(deps,ci): bump actions/checkout from 4 to 6 (#33)
- `e342cb1` chore(deps,ci): bump docker/setup-buildx-action from 3 to 4 (#34)
- `9cb291d` test(semantic-layer): pin query package at 97% behind a 90% CI gate
- `f7414d9` fix(semantic-layer): repair backspace-corrupted regex in explain table fallback
- `02b4a3c` fix(mutmut): repoint query target from re-export shim to real query package
- `8fa8a14` docs: record outbox coverage gate (4c15d0f, six green)
- `4c15d0f` test(reliability): pin outbox dispatch at 92% behind a 90% CI gate
- `7d3a3c6` docs: record key rotation coverage gate (c65de9d, six green)
- `c65de9d` test(security): pin key rotation at 93% behind a 90% CI gate
- `6c779ee` docs: record auth manager gate + F-3 completion (e6914fa, six green)
- `e6914fa` fix(ci): use coverage run for auth manager gate to dodge duckdb-under-cov
- `a78d141` test(security): pin auth manager at 94% behind a 90% CI gate
- `d191694` docs: record rate limiter coverage gate (5a72476, six green)
- `5a72476` test(security): pin rate limiter at 98% behind a 90% CI gate
- `242fbdf` docs: record PII masking coverage gate (6400a83, six green)
- `6400a83` test(security): pin PII masker at 99% behind a 90% CI gate
- `ccbf230` docs(handoff): refresh to HEAD 5936f8d, close F-6 HEAD-drift
- `5936f8d` test(auth): unit-cover pure security logic in auth manager
- `f393cce` docs(state): record strict-typing inversion + mutmut target, close cadence
- `6ae7936` test(security): pin sql_guard into mutmut targets + guard path rot
- `25d9f6b` refactor(mypy): invert strict typing to the global default
- `7f978a7` docs: record GitHub Releases v1.2-v1.4 creation, sync release/state docs
- `475e984` docs(state): record 2026-06-03 audit + safe-fix batch
- `9f11417` test(security): pin sql_guard at 100% coverage behind a 90% CI gate
- `10c37a6` docs(changelog): record NL->SQL guard fix, mutmut repoint, alerts strict slice
- `7eb8461` fix(security): reject DuckDB scan funcs parsed as typed nodes in NL->SQL guard
- `1480a32` fix(mutmut): point paths_to_mutate at the real auth modules
- `af37432` refactor(api): promote alerts dispatcher to strict mypy
- `09cc0ea` docs(state): record api main strict slice
- `8032e24` refactor(api): promote app main to strict mypy
- `28acdf9` fix(api): preserve admin route response models
- `8e58854` refactor(api): promote admin router to strict mypy
- `da1bcfb` docs(state): record mac docker restore
- `0d733e7` docs(state): record serving cache strict mypy slice
- `fb7c4e8` refactor(serving): promote cache to strict mypy
- `ebbe44a` docs(state): record event producer strict mypy slice
- `890b30f` refactor(ingestion): promote event producer to strict mypy
- `154eb0c` docs(state): record event schemas strict mypy slice
- `fc01360` refactor(ingestion): promote event schemas to strict mypy
- `5fecb1b` ci: gate event producer coverage
- `42c1f02` docs(tasks): record alerts dispatcher second opinion prompt
- `12d20d9` docs(state): record webhook dispatcher strict mypy slice
- `66bc820` refactor(api): promote webhook dispatcher to strict mypy slice
- `ee2a6d0` docs(tasks): record webhook dispatcher second opinion prompt
- `e53e0d3` refactor(api): promote admin ui router to strict mypy slice
- `3b19067` docs(state): record stream strict mypy slice
- `3b2078a` refactor(api): promote stream router to strict mypy slice
- `279332e` docs(state): record slo strict mypy slice
- `7a9379d` refactor(api): promote slo router to strict mypy slice
- `fba74b3` docs(state): record lineage strict mypy slice
- `d45ec9b` refactor(api): promote lineage router to strict mypy slice
- `bc88e47` docs(state): record analytics strict mypy slice
- `271b82c` refactor(api): promote analytics middleware to a strict mypy slice
- `305cbc4` docs(state): record versioning strict mypy slice
- `eb5919e` refactor(api): promote versioning helpers to a strict mypy slice
- `3eedbf9` docs(state): record security strict mypy slice
- `44df329` refactor(api): promote security helpers to a strict mypy slice
- `9302129` docs(state): record rate limiter strict mypy slice
- `b0c784f` refactor(api): promote rate limiter to a strict mypy slice
- `34d99da` docs(plan): record open questions closure plan
- `6866f68` docs(state): record search strict mypy slice
- `3d8c2e8` refactor(api): promote search router to a strict mypy slice
- `e2dd257` docs(state): record batch strict mypy slice
- `0729fe5` refactor(api): promote batch router to a strict mypy slice
- `5790bc5` docs(state): record agent query strict mypy slice
- `0cdac06` refactor(api): promote agent query router to a strict mypy slice
- `84c63dc` refactor(api): promote contracts router to a strict mypy slice
- `5f61fd3` refactor(api): promote alerts router to a strict mypy slice
- `45d3fc5` docs(openapi): refresh webhooks response schemas
- `452d120` refactor(api): promote webhooks router to a strict mypy slice
- `0abb206` docs(state): record dead-letter router strict mypy slice
- `e92a6eb` refactor(api): promote dead-letter router to a strict mypy slice
- `0759fc6` docs(security): clarify TLS termination boundary
- `5926d8e` feat(sdk): expose latest version header
- `c2f4db5` docs(api): note sdk version header accessors
- `0e47794` feat(sdk): expose deprecated version header
- `ed50b2d` docs(dv2): clarify recording-day cluster resume
- `20fbba3` docs: clarify container smoke required-check gap
- `1b122cf` ci: stabilize container build smoke check name
- `eadbd0b` docs(state): record aws no-budget boundary
- `93b04b7` docs(state): record codex audit closeout
- `65863f8` fix(docker): carry security pins into api image

**Released:** `v1.4.0` live on PyPI (`agentflow-runtime`, `agentflow-client`)
and npm (`@yuliaedomskikh/agentflow-client`) since 2026-05-24T21:05Z.
Prior releases v1.3.0/v1.2.0/v1.1.0 still available on the same
registries; see `docs/dv2-multi-branch/RELEASE_STATUS.md` for the
full table.

This is the top-level entry point for picking up the project cold. The
DV2 multi-branch demo has its own scoped handoff at
[`dv2-multi-branch/SESSION_HANDOFF.md`](dv2-multi-branch/SESSION_HANDOFF.md) —
this document is the whole-project view.

## How to start a new session

Run these PowerShell commands first; they orient you in under a minute:

```powershell
cd D:/DE_project
git fetch origin main
git log --oneline origin/main -10
gh run list --branch main --limit 6 --json status,conclusion,workflowName,headSha | python -c "import sys,json; [print(f\"{r['conclusion'] or r['status']:11s} {r['workflowName']:25s} {r['headSha'][:7]}\") for r in json.load(sys.stdin)[:6]]"
gh pr list --state open --limit 15
```

In order, those tell you:

1. **Last 10 commits on `main`** — where state is and what just landed.
2. **All six main workflows** (CI / Security Scan / Load Test / E2E Tests /
   Staging Deploy / **Contract Tests**) on the current HEAD — never skip
   Contract Tests when verifying green; it has a path filter that
   bypasses `pyproject.toml`-only commits and a stale red there has
   already burned us once (see Lessons below).
3. **Open PRs** — currently expected to be empty. See "Open work" for
   Dependabot queue rules when new PRs appear.

For DV2 multi-branch demo work specifically, also read
`docs/dv2-multi-branch/SESSION_HANDOFF.md` — it has the iMac/Lima
cluster credentials, asciinema cast pipeline, and the five CH
`MaterializedPostgreSQL` pitfalls.

## Local Windows Verification Policy

This Windows workstation is a no-Docker host. Do not start Docker Desktop,
`docker compose`, `docker build`, kind, Helm live validation, chaos tests, or
Docker-dependent full pytest here; Docker has been observed to hang local
processes on this machine.

Use `$env:SKIP_DOCKER_TESTS='1'` for broad local pytest. Run Docker-heavy gates
on the Mac runner or in CI, and record the command, commit SHA, and result before
claiming full Docker coverage. If only this Windows machine was used, report the
state as `local no-Docker green; Docker-heavy verification pending on Mac/CI`.

Current Mac Docker evidence, collected 2026-05-30 on `julia@192.168.1.133`, is
historical evidence for the Docker build/compose surface rather than current
HEAD evidence: the iMac is reachable over SSH, Lima `docker` is running Docker
Engine `29.5.2`, and Docker Compose CLI plugin `v5.1.4` is installed in the
user Docker CLI plugins. The checkout `/Users/julia/agentflow-docker-check` was
reset to `origin/main` at `ffeb423`. `docker build -f Dockerfile.api -t
agentflow-api:mac-docker-smoke-ffeb423 .` passed. `docker compose -p
agentflow-e2e-mac -f docker-compose.e2e.yml up -d --build --wait
agentflow-api` also passed; Redis, Postgres, Kafka, and API reached Docker
`Healthy`, and `/v1/health` reported `kafka:healthy` plus
`duckdb_pool:healthy`. The aggregate API health stayed `unhealthy` because
Flink, Iceberg, freshness, and quality signals are not part of the e2e compose
stack. Cleanup with `down -v` completed and only the pre-existing `hq-demo` kind
containers remained. The repo has no registered self-hosted GitHub Actions
runners (`total=0`). A repo-local Python 3.11 venv now exists at
`/Users/julia/agentflow-docker-check/.venv-mac-docker`; after commit `677de80`
the Mac compose smoke `AGENTFLOW_E2E_MODE=compose
AGENTFLOW_E2E_TIMEOUT=180 .venv-mac-docker/bin/python -m pytest
tests/e2e/test_smoke.py -v --tb=short -p no:schemathesis --basetemp
.tmp/mac-e2e-smoke-basetemp -o cache_dir=.tmp/mac-e2e-smoke-cache` passed with
`10 passed in 121.10s`. The fix keeps Linux/CI callback URLs on
`host.docker.internal` and uses Lima's `host.lima.internal` on Darwin unless
`AGENTFLOW_E2E_CALLBACK_HOST` is set explicitly.

Current 2026-05-30 Codex audit remediation evidence through HEAD `65863f8`:
`0ea3da6` closed OpenAPI export drift; `a261b95` refreshed README and
`docs/dv2-multi-branch/RELEASE_STATUS.md` to `v1.4.0` registry reality;
`672c8fd` bounded streamed request bodies without `Content-Length`; `c61a28c`
removed the mojibake box-drawing regex in the DuckDB explain-plan scrubber;
`dce7115` regenerated `docs/quality.md` through local no-Docker reporting;
`8c96128` ignored locked local temp roots; and `7b0f924`/`65863f8` made
`docker-compose.prod.yml` reuse `Dockerfile.api` while preserving the runtime
security pins. Local evidence includes OpenAPI check, full Windows no-Docker
pytest (`846 passed, 32 skipped`), quality-report tests and generator,
prod-compose/security workflow policy tests (`22 passed`), targeted ruff/format,
`mypy scripts\quality_report.py`, and `git diff --check`. GitHub evidence on
`65863f8`: push CI, Contract Tests, Security Scan, E2E Tests, and Staging Deploy
completed successfully. Push Load Test run `26677145590` failed from broad p99
runner slowdown; manual Load Test reruns `26677294150` and `26677355752` on the
same SHA both completed successfully, satisfying the load-regression runbook's
runner-variance recheck.

## Compact-Safe Autonomous Start

If the next chat session starts with missing or compacted context, do not ask the
operator to reconstruct this session. Treat the checked-in docs as the durable
handoff and rebuild state from the repo:

```powershell
cd D:/DE_project
git status --short --branch -uno
git rev-parse --short HEAD
git log --oneline -8
```

Then read, in this order:

1. `AGENT_STATE.md`
2. `docs/SESSION_HANDOFF.md`
3. `docs/operations/local-verification-matrix.md`
4. `AUTOPILOT.md`
5. `docs/operations/autonomous-compact-safe-process.md`
6. `BACKLOG.md`
7. `.autopilot/BLOCKED.md`, if present
8. `next-session-autonomous-local-plan.md`

Use the copy-paste kickoff prompt and the work-selection priority order in
[`next-session-autonomous-local-plan.md`](../next-session-autonomous-local-plan.md)
— that file is the canonical uninterrupted-session starter. Short form:

```text
D:\DE_project. Работай автономно и без перерыва, решения принимай сам. Восстанови состояние из AGENT_STATE.md, docs/SESSION_HANDOFF.md, docs/operations/local-verification-matrix.md, AUTOPILOT.md, BACKLOG.md и next-session-autonomous-local-plan.md (не опирайся на неполный chat compact). Бери следующий безопасный атомарный пункт по приоритету из плана, TDD-фикс, no-Docker верификация, коммит явными pathspec, push origin main после чистого статуса + git diff --check, жди CI зелёным перед следующим коммитом. НЕ запускай Docker тут (Mac/CI). Внешнее/AWS не трогай (нет карты/бюджета). Не спрашивай "что дальше" пока есть безопасный пункт; не стекай однотипные мелкие коммиты. Стоп только на named boundary или когда безопасных локальных пунктов нет.
```

Continuation rules:

- Do not start Docker Desktop or any Docker-backed gate on this Windows host.
- Prefer closing current dirty WIP before choosing new work.
- If compaction loses details, re-read the durable docs above and continue from
  repo evidence instead of asking for a recap.
- Do not repeat a blocked item family just to refresh timestamps, HEAD hashes,
  branch-ahead counts, or handoff prose.
- Delegate admin/external gates to an admin-capable tool when available, but
  integrate only real non-secret evidence.
- Local commits are autonomous after scoped verification. Ordinary
  `git push origin main` is authorized for the human-agent autonomous session
  after clean tracked status and `git diff --check`. Force-push, deploy,
  release, publish, Terraform apply, scheduler/env changes, other branches/tags,
  and destructive git operations remain explicit remote/destructive boundaries.
- Stop only for a hard-stop trigger, real local blocker with no safe local
  candidate left, unexpected dirty-file conflict, or an explicit
  remote/destructive boundary with no safe local prep remaining.

Pre-refresh closeout evidence: `git status --short --branch --untracked-files=no`
was clean at `main...origin/main`, HEAD was `0d733e7`, and the latest six
workflows for `0d733e7` were green: CI `26728505643`, Security Scan
`26728505651`, Load Test `26728505661`, E2E Tests `26728505657`, Staging Deploy
`26728505691`, and manually dispatched Contract Tests `26728522414`. The local
process audit found no live `mypy`, `pytest`, `ruff`, `run_load_test`,
`uvicorn`, or `locust` process from `D:\DE_project`; the only matching command
line was the audit PowerShell itself. The next-session checklist is
`next-session-autonomous-local-plan.md`.

## Open work — priorities

### Tier A — actionable in-repo (no external blocker)

**Strict mypy slices extended + latent bugs found (`f977317`→`fb7c4e8`, 2026-06-01):**
`src.ingestion.schemas.events`, `src.ingestion.producers.event_producer`,
`src.serving.cache`,
`src.serving.api.auth.*`,
`src.quality.monitors.*`, `src.serving.semantic_layer.*`,
`src.serving.backends.*`, `src.serving.api.middleware.*`,
`src.serving.api.routers.deadletter`, `src.serving.api.routers.webhooks`, and
`src.serving.api.routers.{alerts,contracts,agent_query,batch,search}`, plus
`src.serving.api.rate_limiter`, `src.serving.api.security`,
`src.serving.api.versioning`, `src.serving.api.analytics`,
`src.serving.api.routers.lineage`, `src.serving.api.routers.slo`, and
`src.serving.api.routers.stream`, plus `src.serving.api.routers.admin_ui` and
`src.serving.api.webhook_dispatcher`, plus `src.serving.api.routers.admin` and
`src.serving.api.main`
now set `disallow_untyped_defs = true` (joining `src.quality.validators.*`);
`tests/unit/test_typing_policy.py` pins each and `mypy src` is clean on 99
files. Typing the monitors slice surfaced a real tombstone bug in
`FreshnessMonitor._process_message` (now skipped with `reason="empty_message"`,
100% module coverage). The webhooks slice required a generated
`docs/openapi.json` refresh because FastAPI now exposes object response schemas
for the typed router returns. The admin router slice also proved the same
FastAPI return-annotation/OpenAPI interaction: `8e58854` initially caused
OpenAPI drift, and `28acdf9` preserved the prior route contract with explicit
`response_model=None`. The API main slice used the same `response_model=None`
guard for top-level routes and fixed a reload-state coupling by reading
`request.app.state` in `changelog()` and `catalog()` instead of the
module-global `app`. The batch, search, rate-limiter, security, versioning,
analytics, lineage, SLO, stream, admin UI, and webhook dispatcher slices were
pure annotation and produced no OpenAPI drift. The event-schemas
slice was also pure annotation, adding `ValidationInfo` to
`OrderEvent.total_matches_items()`. The event-producer slice was also pure
annotation, covering `DecimalEncoder.default()`, the Kafka delivery callback,
and `run_producer()`. The cache slice was also pure annotation, covering
`QueryCache.__init__()` client injection. Local evidence included red/green
policy tests, targeted event-schema, producer, and cache tests, full `mypy src
--no-incremental`, ruff/format, event producer coverage at 96.43%, broad
no-Docker unit tests (`614 passed, 1 skipped` after the cache slice), and `git
diff --check`. GitHub evidence on `fc01360`: CI
`26727188068`, Contract Tests `26727188052`, E2E Tests `26727188055`, Load Test
`26727188040`, Security Scan `26727188061`, and Staging Deploy `26727188070`
all completed successfully. GitHub evidence on `890b30f`: CI `26727775488`,
Contract Tests `26727775500`, E2E Tests `26727775494`, Security Scan
`26727775502`, and Staging Deploy `26727775493` completed successfully; push
Load Test `26727775487` failed on p99 spikes with 0.00% functional failures,
then same-SHA reruns `26727841007` and `26727894286` both passed, so this is
recorded as runner variance under `docs/runbooks/load-test-regression.md`.
GitHub evidence on `fb7c4e8`: CI `26728301122`, Contract Tests `26728301116`,
E2E Tests `26728301110`, Load Test `26728301106`, Security Scan `26728301120`,
and Staging Deploy `26728301115` all completed successfully.
State-refresh evidence on `0d733e7`: CI `26728505643`, Security Scan
`26728505651`, E2E Tests `26728505657`, Load Test `26728505661`, Staging Deploy
`26728505691`, and manually dispatched Contract Tests `26728522414` all
completed successfully. The Staging Deploy run initially failed in kind
bootstrap checksum validation and passed on rerun of the same workflow run, so
record it as CI infrastructure variance rather than code variance.
Admin router evidence on `28acdf9`: local OpenAPI export check passed, strict
admin mypy passed, full `mypy src` passed on 99 files, targeted admin/auth/API
tests passed with 36 tests, broad no-Docker unit tests passed with 615 passed
and 1 skipped, and targeted ruff/format plus `git diff --check` passed.
GitHub evidence: CI `26764466357`, Contract Tests `26764465421`, E2E Tests
`26764467344`, Security Scan `26764465393`, and Staging Deploy `26764468572`
completed successfully. Push Load Test `26764465394` failed with broad p99
slowdown and 0.00% functional failures; same-SHA rerun `26764636429` passed,
so it is runner variance under `docs/runbooks/load-test-regression.md`.
API main evidence on `8032e24`: local OpenAPI export check passed, strict main
mypy passed, full source-tree mypy passed when split by top-level package after
the monolithic Windows command exited `-1` without type diagnostics, targeted
app/lifespan tests passed with 45 tests, broad no-Docker unit tests passed with
616 passed and 1 skipped, and targeted ruff/format plus `git diff --check`
passed. GitHub evidence: CI `26766623636`, Contract Tests `26766623641`, E2E
Tests `26766623602`, Load Test `26766622645`, Security Scan `26766623507`, and
Staging Deploy `26766623441` all completed successfully.
After the cache slice, local non-gated strict candidates
`src/processing/iceberg_sink.py`, `src/serving/db_pool.py`,
`src/serving/masking.py`, `src/serving/semantic_layer/catalog.py`, and
`src/serving/semantic_layer/query/engine.py` were checked with narrow strict
commands and were already clean; avoid override-only churn there.
The API-side AST baseline after the API main slice is 2 untyped functions in
`alerts/dispatcher.py`, still on the required-second-opinion list. The next
attempted API-side candidate,
`src.serving.api.alerts.dispatcher`, did not receive a Claude review because
`claude -p` closed the socket. The exact prompt and non-secret error are
recorded in `second-opinion-alerts-dispatcher.md` at HEAD `42c1f02`; no alerts
dispatcher code was changed, and that prompt should not be retried unchanged
without new evidence that Claude is available.
`src/processing/flink_jobs` remains the separate 15-error / 12-function
PR-#23/Docker-gated slice. Load Test on the security commit
`44df329` failed once on p99 spikes with 0.00% functional failures and then
passed two same-SHA reruns (`26703049909`, `26703112750`), so record it as
runner variance per `docs/runbooks/load-test-regression.md`.
The API remainder is a large multi-file grind that is a deliberate stopping
point, incremental not load-bearing. Two gotchas this session: (1) the
Edit tool flips/corrupts EOL on this repo — edit source byte-level and re-check
CRLF + `git diff --check` + staged blob size; (2) the bandit baseline is
line-keyed, so a line-shifting edit (e.g. a new import) to a file with a
baseline finding breaks Security Scan + the CI `test_bandit_diff` test until
`.bandit-baseline.json` is refreshed.

**Coverage cadence (`5fecb1b`, 2026-06-01):** `src.ingestion.producers.event_producer`
now has a CI `test-unit` scoped coverage gate at 90%, pinned by
`tests/unit/test_coverage_policy.py`. Local evidence: the red policy test failed
before the CI step existed, then passed; `tests/unit/test_event_producer.py`
passed with 96.39% module coverage at `--cov-fail-under=90`; combined policy +
event producer tests passed with 12 tests; `SKIP_DOCKER_TESTS=1 python -m
pytest tests/unit -p no:schemathesis --continue-on-collection-errors` passed
with 611 passed, 1 skipped. GitHub evidence on `5fecb1b`: CI, Contract Tests,
E2E Tests, Load Test, Security Scan, and Staging Deploy all completed
successfully.

**M-C4 hashed-key guidance now enforced (`e444ecf`, 2026-05-30):**
`AuthManager.load()` emits a `hashed_key_count_exceeds_guidance` warning once
more than `HASHED_KEY_SOFT_LIMIT` (10) hashed keys are configured, turning the
docs-only M-C4 soft cap into a runtime signal operators can alert on before the
cold-start bcrypt latency cliff. TDD via `structlog.testing.capture_logs`
(stdlib factory is not active in unit tests, so `caplog` does not see structlog
events). Six main workflows green. The full hashed-key-lookup rewrite (bcrypt
hash-format swap) stays deferred — it needs the format change, not a perf tweak.

**Autonomous local follow-up closeout:** the post-audit safe local queue is
closed through `0759fc6`. `1b122cf` pins the PR Docker smoke check name as
`build-smoke` and covers it with unit tests; `20fbba3` records that
`build-smoke` is still not a required branch-protection check; `ed50b2d`
clarifies the DV2 recording-day cluster resume path; `0e47794` and `5926d8e`
add Python SDK accessors for deprecated/deprecation-warning/latest version
headers; `c2f4db5` documents the SDK accessors; `0759fc6` clarifies that TLS is
terminated at the edge/ingress boundary rather than inside FastAPI. No Docker,
AWS, Terraform, deploy, publish, paid service, secret, or production operation
was used. If no new dirty WIP, failed workflow, owner evidence, admin
authorization, or bounded local assignment appears, do not repeat this closed
family.

**Six Tier A Dependabot PRs landed in session 18** (#24 mypy,
#8 terraform-aws, #10 typescript, #17 github-script, #20
download-artifact, #21 docker/build-push, #12 vitest). Resolver
smoke (`pip install --dry-run -e ".[dev,cloud,contract]"`) green on
HEAD `2333104`. **Six more landed in session 26** (#25 schemathesis
4.20, #26 setup-terraform v4, #27 docker/login v4, #28 upload-artifact
v7, #29 setup-helm v5, #30 setup-node v6); two pinned unit-test
assertions had to be pushed onto the dependabot branches before
`--admin --squash`. See "Recent activity" below for SHAs.

**Dependabot queue currently empty.** Next batch will open on the
weekly Monday 06:00 MSK schedule (see `.github/dependabot.yml`).

**Generated external gate pack:** after the operator clarified that external
gate material should be generated/modelled rather than pursued through real
outreach, `docs/operations/generated-external-gate-pack-2026-05-30.md` now
contains the synthetic package for zero-budget AWS posture, production CDC
rehearsal, five PMF interviews, pricing/WTP review, production-hardware
benchmark report shape, and external pen-test attestation rehearsal. Treat that
pack as generated planning material only. It does not close real external
evidence gates.

**AWS/Terraform boundary:** the operator has no foreign payment card for AWS
signup and no AWS budget. Treat AWS/Terraform apply as explicitly out of scope,
not as a recurring project deficiency or active blocker, unless the operator
later provides a budget, AWS account/payment path, and explicit reintroduction.
For the DV2/X5 demo, use the documented S3-compatible cold tier with HF Datasets
or Backblaze B2 for derived/anonymized parquet; do not propose AWS as required
storage for that dataset.

**Local autopilot status:** the scheduled task is installed as
`scripts/autopilot.ps1 -Planner codex -ExitZeroOnBlocked -Commit`.
The latest scheduled-mode run wrote `.autopilot/BLOCKED.md` and exited
cleanly because no bounded safe local task remained. Do not remove that
runtime blocker merely to keep the loop moving; provide external owner
evidence for one blocked gate or assign a new bounded local task with
allowed paths and local verification.

**Two Dependabot PRs closed as `wait-for-upstream`** — neither is
mergeable without external/upstream movement that this repo can't
trigger:

| PR | Bump | Close reason + re-open condition |
|----|------|--------------------------------|
| `#23` (closed) | `apache-flink` 1.19.1 → 2.2.1 (`flink` extra) | Apache docs explicitly state "There is no SQL jar (yet) available for Flink version 2.2" / "There is no connector (yet) available for Flink version 2.2" (https://nightlies.apache.org/flink/flink-docs-release-2.2/docs/connectors/datastream/kafka/). The `[flink]` extra exists to power `src/processing/flink_jobs/{stream_processor,session_aggregator}.py`, both of which depend on `pyflink.datastream.connectors.kafka` + the bundled `flink-sql-connector-kafka` JAR. Merging would ship a non-functional extra. **Re-open when**: `flink-sql-connector-kafka` releases a `-2.x` suffix JAR on Maven Central. **Flink 2.0 API changes already mapped** (in the PR close comment + session memory): `ExternalizedCheckpointCleanup` → `ExternalizedCheckpointRetention` (`pyflink.datastream.externalized_checkpoint_retention`, used via `set_externalized_checkpoint_retention()` instead of `enable_externalized_checkpoints()`), `pyflink.common.time.Time` removed (use `Duration.of_millis()` — already imported in `Dockerfile:35`), Scala 2.12 dropped in 2.0 (bump `SCALA_VERSION=2.12` → `2.13` in `Dockerfile:4`). Code-prep is ~half a day once the connector unblocks |
| `#11` (closed) | `python` 3.11-slim → 3.14-slim (`Dockerfile.api`) | Docker build is not exercised by any required CI workflow. `container-attestation.yml` now has a PR `build-smoke` job for Dockerfile / pip-surface changes, but `build-smoke` is not yet in branch protection's required status checks, so a broken `docker build` could still land if the non-required check is bypassed. Ecosystem compat is uneven (`apache-flink`, `dagster`, `langchain-core` have spotty 3.14 wheel coverage, and `slim-bookworm` lacks gcc so source-build fallback fails). **Re-open when**: either `build-smoke` becomes a required check on `pull_request` events OR all heavy extras (`[flink]`, `[ml]`) have published 3.14 wheels on PyPI |

### Kimi audit closure ledger (`audit_kimi_25_05_26.md`)

Live source-of-truth for which findings are closed and which remain.
Audit file itself stays in the repo root for reference. Sessions
22→25 audit closures shipped to `origin/main` in session 26 (push
`dc74bd1`). The ledger below still reflects audit state as of HEAD
`da52ca1`; the 2026-05-29 local refresh found no owner-provided
external evidence that would change blocked or deferred gate status.

| Finding | Status | Where | Notes |
|---------|--------|-------|-------|
| R2 contract.yml paths | closed s21 | `22b1be9` | TF/sdk-ts/Dockerfile paths added |
| R4 CDC connector coverage | closed s21 | `123587d` | 0% → 100% via `tests/unit/test_cdc_connector_configs.py` |
| R5 branch coverage gate | closed s21 | `325e311` | `--cov-branch` added to CI |
| R6 container PR smoke | closed s21 | `1edec1e` | `build-smoke` on PR |
| R7 Flink-jobs mypy | closed s21 | `23397ac` | `ignore_errors` dropped; 3 type errors fixed |
| H-C1 DuckDB f-string SQL | closed s23 | `356715e` | bare-or-quoted identifier regex; `explain` parses via sqlglot. **CX P1 caught quoted `"acme"."orders_v2"` regression pre-commit.** |
| H-C2 ClickHouse regex + HTTPS | partial s25 | `8198af4` | string-literal masking + `ssl.create_default_context`. Full sqlglot transpile + `urlopen→PoolManager` still deferred |
| H-C3 duplicate usage records | closed s22 | `64252d3` | `audit_publisher.publish` moved out of DuckDB retry loop |
| H-C4 AuthManager memory leak | closed s23 | `356715e` | `_sweep_expired_windows()` on load + clear_failed_auth; plaintext cache purge |
| M-C1 search rebuild crash | closed s22 | `64252d3` | lifespan rebuild wrapped, periodic still scheduled |
| M-C2 SessionAggregator per-event | DEFERRED | — | Flink hot-path; gated behind PR #23 Flink 2.x wait-for-upstream |
| M-C3 double `json.loads` Flink | DEFERRED | — | same gate as M-C2 |
| M-C4 O(n) hashed key auth | partial s26 | `docs/perf/auth-bench-2026-05-26.md` | Measured: bcrypt-12 N=20 hit-last p95 = 8146 ms (exceeds 1100 ms load gate). Steady-state mitigated by plaintext cache (`manager.py:284`) + failed-auth backoff. Cold-start / SIGHUP / DoS remain; ≤ 10 hashed-key guidance documented. Rewrite needs hash-format swap — out of scope |
| M-C5 O(n) rate window trimming | closed s26 | `docs/perf/auth-bench-2026-05-26.md` | Measured: 6 μs p95 at W=120 (default), 0.45 ms p95 at W=10000 pathological. Constant factor (list-comp on floats) makes O(n) invisible at realistic scale. Ring-buffer rewrite skipped — gains negligible vs added complexity |
| L-C1 `"pass"+"word"` obfuscation | closed s24 | `bbc9827` | renamed to `"password"` + `# noqa: S105` |
| L-C2 hardcoded MySQL server.id | closed s24 | `bbc9827` | `AGENTFLOW_MYSQL_SERVER_ID` env override |
| L-C3 redundant `or event_type == prefix` | closed s24 | `bbc9827` | both validators |
| L-C4 DB utils in middleware file | closed s26 | new `src/serving/api/auth/usage_table.py` | `ensure_usage_table` / `record_usage` / `usage_by_tenant` extracted (~135 LOC); middleware drops 4 dead imports (`duckdb`, `time`, `pathlib.Path`, `AuthManager`); manager lazy imports + test_audit_publisher monkeypatch sites repointed; 543/543 unit green |
| R8 stale `coverage.xml` | closed s22 | `64252d3` | file deleted locally (was always in `.gitignore:43`, audit read stale state) |
| R9 `.tmp/` cleanup | non-issue | — | audit claim "not in `.gitignore` for that path" is false — `.gitignore:53` covers `.tmp/`. Accumulation is local-disk-only and pytest-basetemp managed; treat as `git clean -fdx .tmp/` housekeeping, not a repo gap |
| R10 `node_modules/` in root | non-issue | — | already in `.gitignore:62`, untracked — audit read stale state |

**Next audit-driven session is unblocked on:** none of the deferred
items require autonomous further work in this codebase. M-C2/M-C3
need Flink 2.x to ship a compatible kafka connector JAR (PR #23
wait-for-upstream). M-C4 has documented guidance (≤ 10 hashed-key
soft cap, plaintext cache + failed-auth backoff handle steady-state)
and a rewrite needs the hash-format swap. Pick up H-C2 full sqlglot
transpile only when integration coverage against a live ClickHouse
is available — masking + HTTPS cert validation already address the
two security concerns the audit raised.

### Tier B — what these gates actually mean

These were carried as a generic "user-gated" bucket in earlier
handoffs; on re-inspection only A04 / A05 are *waiting* on anything,
and what they're waiting on is a real production deployment that
doesn't exist yet. A03 was actually closed in session 9.

| Gate | Real status | Where the decision/runbook lives |
|------|-------------|----------------------------------|
| **A03** CI hardware-gap | **Closed s9 (`e38a6e5` + `docs/perf/ci-hardware-gap-2026-05-24.md`)** — Decision is "Accept divergent perf thresholds between local + CI", thresholds raised to 900 / 1100 / 1200 ms in `tests/load/thresholds.py`, all subsequent load-test runs green. Re-open only if a real prod tenant complains about CI-vs-prod divergence | `docs/perf/ci-hardware-gap-2026-05-24.md` § Decision |
| **A04** prod CDC source onboarding | **Not applicable until a prod deployment exists.** The runbook is documentation-complete (decision-record template, network/secret/monitoring/rollback owner slots, sample tfvars). It "executes" the day someone wires a real source DB — until then there is no input to gate on | `docs/operations/cdc-production-onboarding.md` § Required Decision Record |
| **A05** prod K8s cluster access | **Not applicable until a prod cluster exists.** Test harness already honours external `KUBECONFIG` via `AGENTFLOW_LIVE_REUSE_CLUSTER=1`; once a real EKS/GKE/AKS context is wired into CI as a secret, the parametrized live-validation suite picks it up with zero code changes | `tests/integration/test_helm_values_live_validation.py` |

In short: A03 is done; A04 / A05 are documentation-complete and
behavioural-complete and just don't have a customer yet. There is no
hidden engineering task here — only a missing real-prod deployment.

### Repo settings (session 18f, admin actions)

- `allow_auto_merge: true` — `gh pr merge <N> --auto --squash` is now
  supported. Use this for any Dependabot PR whose required checks
  will pass on the rebased SHA; GitHub will merge automatically once
  CI is green without needing a wakeup-loop on the human side.
- `delete_branch_on_merge: true` — squash-merged branches are removed
  automatically; `--delete-branch` flag on `gh pr merge` is no longer
  required (still harmless if you forget and pass it).

### Pre-conditions before re-enabling Tier B work

Recorded from the session 18g CXKM audit (CX P2 confirmed + KM P1×2,
P2×2, P3×1 solo). All items below are latent — current CI does not
exercise them — but they will surface the moment the gated jobs come
back online.

- **Before re-enabling `terraform-apply.yml` plan / apply jobs (A04/A05/A03
  unblock):**
  - **Provider v6 install verified 2026-05-25 (session 19)** — ran
    `terraform init -backend=false -upgrade` locally with Terraform
    `v1.15.4` against the `~> 6.46` constraint in `main.tf:7`. The
    provider plugin installed cleanly at `hashicorp/aws v6.46.0`; the
    local `.terraform.lock.hcl` is gitignored
    (`.gitignore:33`), so CI generates its own lockfile per run and
    no commit is required for this verification. The TF code itself
    is already v6-compatible — MSK uses the modern `storage_info /
    ebs_storage_info` nested block, S3 uses the modular
    `aws_s3_bucket_versioning / aws_s3_bucket_lifecycle_configuration`
    / etc. siblings (not the deprecated inline blocks),
    `aws_iam_policy_document` data sources do not set the removed
    `version` attribute, and there are no `aws_s3_bucket_object`
    references. This is historical validation only. The AWS `plan` / `apply`
    jobs remain disabled and are not an active gate under the 2026-05-30
    no-budget/no-card decision. Revisit only if the operator explicitly
    reintroduces AWS with budget, account/payment path, `AWS_TERRAFORM_ROLE_ARN`,
    tfvars, and approval to remove the `if: false` guard.

- **Before pushing a new `agentflow-api` container image to production
  (currently `container-attestation.yml` is `workflow_dispatch` for
  `build-and-sign` / `sign-existing-digest`; session 21 added a
  `build-smoke` job on every PR that touches `Dockerfile*` /
  `pyproject.toml` / `requirements.txt` / the workflow itself):**
  - The PR-level `build-smoke` job does `docker/build-push-action@v7`
    with `push: false` + `load: true` + GHA layer cache, so a broken
    Dockerfile fails the PR instead of landing silently. Local smoke
    on session-21 HEAD produced a 910 MB image in 181 s end-to-end
    against Docker Desktop 29.4.0.
  - Still TODO: promote `build-smoke` to a **required** status check
    via `gh api -X PATCH /repos/brownjuly2003-code/agentflow/branches/main/protection`
    once one PR-run confirms standard-runner timings (held off because
    promoting before the first PR-event run lands would block all open
    PRs; do this in a quiet window). Commit `1b122cf` pins the PR job name to
    `build-smoke`, but did not change branch protection.
  - Running `build-and-sign` end-to-end manually (via
    `gh workflow run container-attestation.yml -f mode=build-and-sign -f confirm=SIGN`)
    is still useful before a release tag — it's the only path that
    exercises v7 runtime defaults (`provenance`, `attestations`) plus
    the cosign keyless flow.

### Anti-tasks — looks like cleanup but isn't

- **Do NOT remove the `try: import yaml / except ImportError: yaml = None`
  blocks** in `src/serving/{masking,backends,api/security,api/auth/*,
  api/alerts/dispatcher,api/routers/slo,api/webhook_dispatcher,
  api/versioning,semantic_layer/contract_registry}.py` and
  `src/ingestion/tenant_router.py`. The runtime checks paired with
  them (`yaml.safe_load(raw) if yaml is not None else json.loads(raw)`
  in `slo.py:58`, `webhook_dispatcher.py:60`, `alerts/dispatcher.py:95`,
  and `if yaml is not None: ...` elsewhere) are an intentional
  JSON-fallback architecture, not dead code. PyYAML is currently
  pinned as a hard runtime dependency in `pyproject.toml`, but the
  fallback machinery survives so the optional-pyyaml posture stays
  available — collapsing it means deciding to lock PyYAML as a hard
  requirement and dropping JSON-config support, which is an
  architectural call, not a chore. Session 18e looked at this and
  deliberately stopped at swapping the `import-untyped` ignores for
  honest `assignment` ignores on the `yaml = None` fallback line.

### Tier C — forward backlog (when there is bandwidth)

- Cut **`v1.5.0`** when real feature changes accumulate. v1.4.0 went
  out 2026-05-24 (PyPI + npm, see `docs/dv2-multi-branch/RELEASE_STATUS.md`).
  `[Unreleased]` in `CHANGELOG.md` already carries five sessions worth
  of code-level audit hardening (s22 H-C3 + M-C1, s23 H-C1 + H-C4,
  s24 L-C1/L-C2/L-C3, s25 H-C2 narrow) and the API-instrumentation +
  Grafana dashboards from s20 — body is ready, just needs a version
  bump + tag when the next product change lands.
- **OTEL observability backfill — partial (2026-05-25 session 19)**:
  - **Pipeline dashboard authored**:
    `infrastructure/observability/grafana/agentflow-pipeline-health.json`
    covers the metrics actually exported by
    `src/quality/monitors/{freshness_monitor,metrics_collector}.py`
    via the Prometheus ASGI mount at
    `src/serving/api/main.py:285`. Five panels: pipeline latency
    p50/p95/p99 by topic (with SLO threshold at 30s), SLA compliance
    ratio bar gauge, Kafka consumer lag, per-component pipeline
    health (mapped to healthy / degraded / unhealthy text), events
    processed running total. The dashboard's `description` field
    documents the gap below. Importable into any Grafana 9+ via UI
    or `grafana-cli` against a Prometheus datasource templated to
    `${DS_PROMETHEUS}`.
  - **Tracing wiring** in `src/serving/api/telemetry.py` (FastAPIInstrumentor
    + HTTPXClientInstrumentor) already exports to any
    `OTEL_EXPORTER_OTLP_ENDPOINT` — no change needed there.
  - **API-surface instrumentation closed in session 20** —
    `agentflow_http_requests_total{method,route,status}` (new
    middleware `src/serving/api/middleware/metrics.py`) and
    `agentflow_auth_failures_total{reason}` (wired into
    `src/serving/api/auth/middleware.py` + `require_admin_key`) now
    feed both runbook references. Sibling dashboard
    `infrastructure/observability/grafana/agentflow-api-health.json`
    authored with the same `${DS_PROMETHEUS}` template (5 panels:
    5xx-by-route, auth-failures-by-reason, 4xx-by-route+status,
    request-rate-by-status-class, auth-failures-cumulative). Note
    cardinality: auth-rejected requests report
    `route=<unmatched>` on the HTTP counter because the FastAPI
    router only populates `scope["route"]` after `call_next`; the
    route-level breakdown for auth lives on
    `agentflow_auth_failures_total` instead. As a side-effect, fixed
    a latent bug where `/metrics` scrape was 401-rejected on the
    trailing-slash variant Starlette redirects to — `_is_exempt_path`
    now covers both forms.
- **OneScreen / proof-pack-tier polish** lives in separate repos; the
  `docs/codex-tasks/` ledger has historical follow-ups if appetite
  appears for cross-cutting cleanup.

## Recent activity — sessions 11 → 17 compressed

All seven sessions shipped to `main` between 2026-05-24 evening and
2026-05-24 night.

| Session | SHAs | Theme |
|---------|------|-------|
| **29–30 (2026-06-03)** | `09cc0ea`, `af37432`, `1480a32`, `7eb8461`, `10c37a6`, `9f11417`, `475e984`, `7f978a7`, `25d9f6b`, `6ae7936`, `f393cce`, `5936f8d` | **Strict-typing cadence CLOSED** — `af37432` promotes the alerts dispatcher (last untyped src API surface), then `25d9f6b` inverts `disallow_untyped_defs` to the global default: `mypy src --disallow-untyped-defs` confirmed `flink_jobs` (PR-#23-gated) is the sole remaining untyped surface, so ~32 per-module overrides collapse to one relaxation; `test_typing_policy.py` rewritten to the inverted invariant with zero redundant `=true` overrides. **Security fix H-6** (`7eb8461`): the NL→SQL guard (`validate_nl_sql`) missed DuckDB scan funcs in projection position — `read_csv`/`read_parquet` parse to typed `exp.ReadCSV`/`exp.ReadParquet`, not `exp.Anonymous`, so `SELECT read_csv('/etc/passwd')` passed; the check now inspects the call name on every `exp.Func` node, parser-shape-agnostic, covered by two new `tests/unit/test_sql_guard.py` cases. **Mutmut path-rot fixed** (`1480a32`, `6ae7936`): `paths_to_mutate` pointed at the deleted `auth.py` and silently mutated nothing — now targets `auth/manager.py` + `auth/key_rotation.py` + `sql_guard.py`, with `test_mutmut_policy.py` asserting every target exists and the security-critical set stays listed. **F-3 coverage floor** (`9f11417`, `5936f8d`): CI `ci.yml` now carries a global `--cov-fail-under=60` floor plus scoped per-module 90% gates (validators, freshness_monitor, event_producer, sql_guard), and `5936f8d` adds 21 direct unit tests for the pure security logic in `auth/manager.py` (`tenant_key_allowed_tables`, `validate_key_material`, `_legacy_env_keys`, `_matches_key_material`). Six main workflows green on `5936f8d`; HEAD even with `origin/main`. |
| **26** | `dc74bd1` (handoff), `d674afa` (#25), `6a30ac7` (#26), `69fd3b3` (#29), `d92938e` (#30), `2322916` (lint catch-up), `d249448` (#27), `da52ca1` (#28), `b7d562c` (handoff), + this perf-bench commit | Tier A Dependabot wave 3 + push of sessions 22–25 audit closures + M-C4/M-C5 perf-baseline closure (`docs/perf/auth-bench-2026-05-26.md`, `scripts/perf/auth_bench.py`). Pushed the 5-commit audit stack to `origin/main` (`64252d3`, `356715e`, `bbc9827`, `8198af4`, `dc74bd1`) — handoff text was stale on "push deferred". Six new Dependabot PRs (#25–#30) opened 2026-05-25T03:46Z, all merged via `gh pr merge --admin --squash`. **Merged green directly**: #25 schemathesis 4.19.0→4.20.0 (minor patch group), #26 hashicorp/setup-terraform 3→4, #29 azure/setup-helm 4.3.0→5.0.0, #30 actions/setup-node 4→6. **Fixed via push to dependabot branch**: #27 docker/login-action 3→4 (test asserted `@v3` → bumped to `@v4` in `tests/unit/test_container_attestation_workflow.py:48`), #28 actions/upload-artifact 4→7 (two asserts bumped in `tests/unit/test_security_workflow.py:34` + `tests/unit/test_performance_workflows.py:40`). Both rebased onto latest main after lint regression surfaced. **Lint regression fixed** in `2322916` — two test files from session 23 H-C1/H-C4 closure (`test_duckdb_backend_sql_hardening.py`, `test_lifespan_search_resilience.py`) had line-length forms ruff 0.x catches but slipped through the owner-bypass push; pure cosmetic line consolidation. **Lesson 5**: when bumping a dependabot-managed major version of a GH Action that pins assertions in unit tests, the test bump must land on the dependabot branch itself, not on main — otherwise the PR's `test-unit` job stays red and `--admin --squash` ships a broken state for one merge cycle. Pushing directly to `dependabot/...` branches with `--force-with-lease` is supported. |
| **11** | `3053576` | `docs/runbooks/` — 5 on-call incident playbooks (api-5xx, auth-401, cdc-lag, load-test-regression, release-rollback) in the same eight-section format and severity ladder as `chaos-runbook.md` |
| **12** | `29d058a`, `576c2d6` | README + helm chart aligned to `v1.3.0` — badge, Highlights/Status under the `v1.1 → v1.3` arc, DV2 triptych, `helm/agentflow` `appVersion` + `image.tag` bumped |
| **13** | `c684e5f` | `sdk/README.md` made version-agnostic — the PyPI page no longer needs a touch-up at every release |
| **14** | `1c6a124` | Public-repo hygiene: `SECURITY.md` + `.github/ISSUE_TEMPLATE/{bug,feature,config}.yml` + `.github/PULL_REQUEST_TEMPLATE.md` |
| **15** | `971be6b`, `3b2425d` | `.github/dependabot.yml` (7 ecosystems) + `.editorconfig`; prefix-fix hotfix dropping `include: scope` after observing the double-tag bug |
| **16** | `6f3c588`, `813764d`, `0c1234b`, `e1b3abe`, `6e7759e`, `921a845`, `bddedee` | Dependabot merge cascade — 7 safe PRs squash-merged (`#9 #13 #14 #15 #16 #19 #22`): spec-relaxations + schemathesis minor + codecov + setup-python actions |
| **17** | `c90511b` | **Hotfix for the regression the cascade introduced** — see Lessons below |
| **18** | `e2a8288`, `a92f261`, `70d2c51`, `997b8fd`, `b152244`, `695bdf5`, `2333104` | Dependabot Tier A wave 2 — 7 majors squash-merged (`#24 #8 #10 #17 #20 #21 #12`): mypy `<3`, terraform-aws `~> 6.46`, typescript 6, github-script v9, download-artifact v8, build-push-action v7 (with `tests/unit/test_container_attestation_workflow.py` v6→v7 assertion bump in `269c52f`/`26e6808`), vitest 4. All resolved cleanly into the cascade-stable resolver from session 17 |
| **18b–e** | `728622c`, `38e77ff`, `84ece1c`, `031ec64` | Follow-ups: `contract.yml` `paths:` broadened to `pyproject.toml` + `sdk/pyproject.toml` + `.github/workflows/**` (closes the silent-cascade gap from session 16-17); `CHANGELOG.md` `[Unreleased]` backfilled with session 18 + 18b entries; type-stub adoption — `types-PyYAML` and `types-redis` added to dev extras, 18 `import-untyped` ignores retired across `src/`. Type-ignore count dropped 20 → 13 (remaining 13 are honest `assignment` ignores for the `yaml = None` / `redis = None` JSON-fallback pattern). Mypy still 0 errors on 105 files |
| **18f** | `3479561` (reverted by `d448c34`), `eeb95e0` | First attempt at `dora.yml` `--branch origin/main` (kept `dora-report` from failing on PR runs) + CHANGELOG backfill for 18c-f. Also repo admin actions: `allow_auto_merge=true`, `delete_branch_on_merge=true` |
| **18g** | `d448c34`, `6f8a28f` | CXKM tri-blocking audit (CX + KM) on sessions 18-18f. CX found that `--branch origin/main` from 18f silently broke `_load_github_runs` and `_load_deployment_log` in `scripts/dora_metrics.py` (their branch filters need plain `main`, not a remote ref). Reverted with a `git update-ref refs/heads/main` prep step instead. KM P2 widened `types-redis<5 → <6`. Three remaining KM findings recorded in the new "Pre-conditions before re-enabling Tier B work" subsection above |
| **18h** | `34faaeb`, `7a53279` | KM P1 fixes from 18g audit: `upload-artifact@v4 → v7` in `terraform-apply.yml` (matches the v8 download bumped in #20) + five new assertions in `tests/unit/test_container_attestation_workflow.py` covering build step `id`, `context`, `file`, `push`, and `tags` shape so v7 schema changes that rename or retype any of these inputs would fail the unit test. Ruff format catch-up in `7a53279` after the initial commit forgot to run it |
| **25** | `8198af4` | Narrow closure of Kimi audit H-C2 (ClickHouse regex SQL translation + missing HTTPS validation). **Skipped** the full sqlglot dialect-translation migration that was on the deferred list — that needs a dedicated session with full integration coverage. **(1) String-literal masking** — `_translate_sql` extracts every `'...'` (including `''`-escaped) literal into placeholders BEFORE the bare-text rewrites (`::FLOAT`, `NOW()`, `COUNT(*)`, `TRUE`/`FALSE`, `CAST(... AS FLOAT)`, etc.), then restores them. The `INTERVAL '<n> <unit>'` rewrite still runs first against raw SQL so quoted intervals still collapse to ClickHouse `INTERVAL N UNIT`. Seven regression tests in `tests/unit/test_clickhouse_backend.py::TestTranslateSqlLiteralProtection` pin the contract against `::FLOAT`, `NOW()`, `COUNT(*)`, `TRUE`, `CAST(... AS FLOAT)`, and `''`-escape forms inside literals. **(2) Explicit HTTPS cert validation** — `secure=True` now builds an `ssl.create_default_context()` (CERT_REQUIRED + check_hostname) and passes it to `urlopen` via `context=` kwarg. Plain-HTTP backends omit the kwarg entirely so existing test mocks with `def fake_urlopen(req, timeout=None)` signatures keep working — `urlopen_kwargs` is built dynamically and only includes `context` when an SSL context exists. Two regression tests cover the secure/insecure paths. **Gates:** ruff clean, mypy 98 source files clean, pytest tests/unit pending background run at commit time. **CXKM:** auto-trigger triage scored 0–2 (no auth/migration/destructive keywords, parallel tests already exist) → single-mode, no external review needed per skill rules. |
| **24** | `bbc9827` | Closed three Low-priority code-level findings from `audit_kimi_25_05_26.md` § 12.3. **(1) L-C2 MySQL `server.id` env override** — `src/ingestion/connectors/mysql_cdc.py` exports `DEFAULT_MYSQL_SERVER_ID = 223345` and a `_resolve_mysql_server_id()` helper that reads `AGENTFLOW_MYSQL_SERVER_ID` env var. Two parallel Debezium MySQL instances pointing at the same source MUST advertise different `server.id` values; the hard-coded constant would silently collide. Default value preserved so existing deployments are unchanged. New regression `test_mysql_server_id_overridable_via_env` in `tests/unit/test_cdc_connector_configs.py` covers env-override + invalid-int fallback + unset-env fallback. **(2) L-C1 obfuscation removal** — `_CONNECT_SECRET_KEY = "pass" + "word"` replaced with the literal `"password"` + `# noqa: S105` + comment documenting that this is the property *key name* in Kafka Connect `FileConfigProvider` `${file:/path:<key>}` syntax (not a credential value). Bytecode collapses `"pass" + "word"` to `"password"` so the prior pattern provided zero real protection — string scanners flagged it anyway. **(3) L-C3 redundant `==` drops** — `event_type.startswith(prefix) or event_type == prefix` simplified to `event_type.startswith(prefix)` in `src/quality/validators/{schema,semantic}_validator.py` (Python's `str.startswith(p)` already returns True for the exact-equality case when `p` is non-empty, so the `or ==` branch was unreachable). **Gates:** ruff clean, mypy 98 source files clean, pytest tests/unit 534 passed. **CXKM:** auto-trigger triage scored 0–2 (no auth/SQL/migration/destructive keywords, parallel tests already exist) → single-mode, no external review needed per skill rules. |
| **23** | `356715e` | Closed two High-priority code-level findings from `audit_kimi_25_05_26.md` § 14.2 — picked H-C1 (SQL injection vector) and H-C4 (memory leak) because both have narrow, well-understood blast radii and clear test surfaces. Deferred: H-C2 (ClickHouse regex→sqlglot — needs broader behaviour regression coverage), M-C2/M-C3 (Flink hot-path optimisations — blocked behind PR #23 Flink 2.x wait-for-upstream), M-C4/M-C5 (auth lookup/window data-structure rewrites — needs perf measurement first). **(1) H-C1 DuckDB f-string SQL hardening** — `src/serving/backends/duckdb_backend.py:table_columns` matches `_IDENTIFIER_RE` which now accepts both a bare `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$` identifier AND a double-quoted DuckDB identifier (`"name"` or `"schema"."name"`). **CX P1 caught a regression** in the initial bare-only regex: `SQLBuilderMixin._quote_identifier` produces double-quoted forms for tenant-scoped tables, and silently dropping them would have broken the fail-closed `_qualify_table` tenant check and made `get_entity_at(..., tenant_id=...)` return `None` for existing tenant tables. Fix landed before commit. `DuckDBBackend.explain` parses its input through `sqlglot.parse(..., dialect="duckdb")` and rejects multi-statement or non-`SELECT` payloads with `BackendExecutionError` before the `EXPLAIN` wrapper runs. Thirteen regression tests in `tests/unit/test_duckdb_backend_sql_hardening.py` parametrize an injection corpus (`"; DROP TABLE"`, `WHERE 1=1`, `--`, `(SELECT 1)`, `UNION`, numeric-prefix, dot-pathology, whitespace) plus the legitimate `main.orders` schema-qualified path and the `"acme"."orders_v2"` tenant-quoted path (regression pin against the CX-caught false reject). **(2) H-C4 AuthManager memory leak** — new private helper `_sweep_expired_windows()` in `src/serving/api/auth/manager.py` purges `_rate_windows` and `_failed_auth_windows` entries whose entire window has fallen outside the cutoff. Called (a) on every `load()` under `_config_lock` (covers SIGHUP / explicit reload), and (b) opportunistically on every successful `clear_failed_auth` call (post-auth hot path is cheap and bounds growth between reloads). `load()` additionally purges `_runtime_plaintext_by_hash` entries for hashes no longer in `_hashed_keys` — revoked/rotated key's plaintext cannot remain pinned across reloads. Six regression tests in `tests/unit/test_auth_manager_memory_bounds.py` cover sweep-on-load, sweep-on-clear, plaintext-cache purge, and idempotency on empty state. **Gates:** ruff clean (one L501 fix on intermediate `stamps =` extraction in the sweep), mypy clean on 98 source files, pytest tests/unit pending background run at commit time. |
| **22** | `64252d3` | Closed the 1-week-immediate code-level findings from `audit_kimi_25_05_26.md` § 14.1. **(1) H-C3 duplicate usage records** — `record_usage` in `src/serving/api/auth/middleware.py:251` now retries only the DuckDB INSERT; `manager.audit_publisher.publish(payload)` runs once after a successful insert and any publish exception is logged (`audit_publish_failed`) rather than re-driving the DB retry loop. Two regression tests in `tests/unit/test_audit_publisher.py` pin both halves of the contract: publish-raises → exactly one insert + publish attempted once; insert-fails-10× → publish never attempted. **(2) M-C1 search rebuild graceful degradation** — `app.state.search_index.rebuild()` in `src/serving/api/main.py:125` is now wrapped in try/except; a catalog/query-engine error during initial rebuild leaves the API up (with `search_index_initial_rebuild_failed` warning) while the 60s periodic rebuilder (which already swallows exceptions) still gets scheduled, so search recovers without a process restart. Regression: `tests/unit/test_lifespan_search_resilience.py`. **(3) R8 stale `coverage.xml` deleted locally** — file was already in `.gitignore:43` and untracked but lingered on disk showing 0%; Kimi audit treated it as live state. R10 (`node_modules/`) was identical — already in `.gitignore:62`, untracked, no action needed. **Deferred to session 23**: H-C1 / H-C2 SQL hardening (DuckDB `table_columns` / ClickHouse regex translation), H-C4 AuthManager memory leak, M-C2 / M-C3 Flink performance — these need narrower scope per finding. CI on the session 22 commit will run lint + test-unit; the `contract` workflow will not re-trigger because only `tests/unit/**` + `src/serving/**` paths changed (both are in the contract.yml `paths` filter already as of session 21 — manually verify run once the commit is pushed). |
| **21** | `22b1be9`, `23397ac`, `325e311`, `1edec1e`, `123587d`, `94ffda8` + this commit | Closed five of the actionable items from the 2026-05-25 Kimi audit (`audit_kimi_25_05_26.md`, available locally) — R2 / R5 / R6 / R7 / R4 narrow. **(1) R2 contract.yml paths broadening** — added `infrastructure/terraform/**`, `sdk-ts/**`, `Dockerfile*` to both `push` and `pull_request` triggers; closes the remaining `--admin` merge workaround from session 18. **(2) R5 branch-coverage gate** — added `--cov-branch` to the main `test-unit` coverage command in `.github/workflows/ci.yml`; local baseline measured on `22b1be9` is **62% combined** (7716 lines / 2010 branches across 510 unit+property tests), so the existing 60% floor keeps passing with a 2pp cushion. The two per-file 90% gates (validators, freshness_monitor) intentionally stay line-only. **(3) R7 Flink-jobs mypy** — removed the `ignore_errors=true` override for `src.processing.flink_jobs.*`; suppressed only the PyFlink-API quirks (`import-untyped`, `no-any-return`, `no-untyped-call`) and fixed the 3 real errors with `cast()` at the JSON-boundary in `session_aggregation.py:from_snapshot/process_event`. mypy now clean on 98 files including all 4 flink_jobs modules. **(4) R6 container-attestation PR smoke** — added `pull_request` trigger on `Dockerfile*` / `pyproject.toml` / `requirements.txt` / the workflow file, plus a new `build-smoke` job that does `docker/build-push-action@v7` with `push: false` / `load: true` / GHA layer cache. Existing `build-push-sign-attest` + `attest-and-sign` gated behind `github.event_name == 'workflow_dispatch'`. Local Docker Desktop smoke ran 181 s on `1edec1e`. New `test_container_attestation_workflow_runs_smoke_on_pull_request` covers the trigger paths + push/load shape. **(5) R4 CDC connector unit coverage** — added 6 pure-Python tests in `tests/unit/test_cdc_connector_configs.py` for `mysql_cdc.py` + `postgres_cdc.py` (both `0% → 100%` combined). `src.ingestion` total went `82% → ~85%`. Deeper R4 (testcontainers / live Debezium) deliberately deferred — the existing GHA Kafka service-container integration job already covers producers/Debezium without a new dep. **(6) Lint hotfix** — `94ffda8` split a PT018 compound assert in the container-attestation test that local file-by-file ruff missed because I only ran the linter on the files I'd just edited rather than `src/ tests/` (the path CI uses). Lesson: the PR-CI `Ruff check` step is the source of truth; run `ruff check src/ tests/` locally before claiming green. **CI on `94ffda8`:** all 14 check-runs green (lint, test-unit, test-integration, helm-schema-live, perf-check, schema-check, terraform-validate, e2e, load-test, staging, bandit, safety, trivy, npm-audit). The `contract` workflow didn't re-trigger because the hotfix only touched `tests/unit/**` which isn't in the paths filter — manually re-ran via `gh workflow run contract.yml --ref main` (run 26376394495, green). Combined commit status stays **`pending`** for `94ffda8` because workflow_dispatch runs don't attach as commit statuses — same lesson as [[feedback_dependabot_workflow_dispatch_attach]]; harmless on `main` (no PR being gated). |
| **20** | `35f584e`, `8ef49ff`, `eea2241` | Closed the bounded API-instrumentation follow-up flagged by session 19. **(1) `agentflow_http_requests_total{method,route,status}`** exported by a new outermost middleware `src/serving/api/middleware/metrics.py`; route label uses the FastAPI path template (`request.scope["route"].path`), with `route=<unmatched>` fallback for requests an earlier middleware short-circuits before the router runs (auth 401/429/503, demo_mode_guard) — documented inline + in the test. **(2) `agentflow_auth_failures_total{reason}`** wired into both `AuthMiddleware` (reasons `key_file_empty`, `rate_limited`, `missing_key`, `invalid_key`) and `require_admin_key` (reasons `rate_limited`, `admin_unconfigured`, `admin_invalid`). Reason vocabulary matches `docs/runbooks/auth-401-spike.md` Detection step 1. **(3) Sibling dashboard** `infrastructure/observability/grafana/agentflow-api-health.json` — 5 panels (5xx-by-route, auth-failures-by-reason stacked, 4xx-by-route+status, request-rate-by-status-class stacked, auth-failures-cumulative bar gauge); pipeline-health dashboard description updated to point at it instead of flagging the counters as missing. **(4) Latent `/metrics` 401 bug fixed** — surfaced by the `/metrics` round-trip unit test: Starlette redirects bare `/metrics` to `/metrics/`, but `_is_exempt_path` only matched the bare form, so Prometheus scrapes were 401-rejected on the redirect target. Widened to cover both `/metrics` and any `/metrics/...` sub-path. **(5) 9 new unit tests** in `tests/unit/test_api_metrics.py` cover every counter branch + `/metrics` exposure round trip; full unit suite now 495/495, mypy 0 errors on 98 files, ruff clean. `8ef49ff` is a no-content chore commit that converted `main.py` back to LF after the Edit tool inadvertently switched it to CRLF — net diff vs `57d84c9` is +603/-2 |
| **19** | `3d9e9e8`, `405f8a3`, `897b928`, `e58693b`, `0d2f6d5`, `d037fbc`, `57d84c9` | Six tracks closed in one session. **(1) A02 protocol-mixin** verified factually complete (0 `[attr-defined]` ignores in `src/`, `disable_error_code` gone from `pyproject.toml`, `mypy src` clean on 96 files) → dropped stale Tier C bullet. **(2) Deferred Dependabot PR closure** — both #23 (apache-flink 2.x) and #11 (python 3.14-slim) closed as `wait-for-upstream` after surfacing the Flink-2.2 Kafka-connector gap (Apache docs confirm no `flink-sql-connector-kafka` 2.x JAR yet — merging #23 would ship a non-functional `[flink]` extra). Flink 2.0 API breakage map (`ExternalizedCheckpointCleanup` → `ExternalizedCheckpointRetention`, `pyflink.common.time.Time` removed, Scala 2.12 dropped) preserved in PR close comments. **(3) v1.4.0 maintenance release CUT** — 10-file bump per RELEASE_STATUS recipe (root + sdk + sdk-ts pyprojects + sdk/__init__.py + package-lock + 2 test assertions + helm Chart appVersion + helm values image.tag); `CHANGELOG.md` `[Unreleased]` → `[1.4.0] - 2026-05-25`; tag `v1.4.0` on `e58693b`; PyPI + npm Trusted Publishers fired (`agentflow-runtime` + `agentflow-client` + `@yuliaedomskikh/agentflow-client` all on `1.4.0` since `2026-05-24T21:05Z`). No runtime API changes vs `v1.3.0`. Local smoke 486/486 `tests/unit/`. **(4) Terraform v6.46.0 provider install verified** locally with `terraform init -backend=false -upgrade` against the `~> 6.46` constraint in `main.tf:7`; no commit needed because `.terraform.lock.hcl` is gitignored (`.gitignore:33`) — CI generates its own per run. The old re-enable path for `terraform-apply.yml` is now archived; under the 2026-05-30 no-budget/no-card decision it is not an active gate. **(5) Grafana pipeline-health dashboard** (`infrastructure/observability/grafana/agentflow-pipeline-health.json`) — five panels over the metrics actually exported by `src/quality/monitors/`: pipeline latency p50/p95/p99 by topic (SLO line at 30s), SLA compliance bar gauge, Kafka consumer lag, per-component health (healthy/degraded/unhealthy mapping), events processed running total. Backs the `cdc-lag.md` runbook directly. HTTP-level panels (`api-5xx-spike.md`, `auth-401-spike.md`) intentionally skipped — referenced metrics (`agentflow_http_requests_total`, `agentflow_auth_failures_total`) not yet defined in `src/`; the dashboard description + Tier C bullet document the bounded follow-up. **(6) Container-attestation behavioural smoke deferred** — Docker Desktop daemon was offline (`docker info` Server section empty) and starting it without explicit user OK was out of scope |

## Lessons (recent, load-bearing)

These are the calluses from sessions 16–18 specifically — keep them
visible when you pick up next.

### 1. Final CI check must include all six main workflows

The required status checks include `contract`, but the **Contract
Tests** workflow has a path filter that excludes `pyproject.toml`. So
a deps-only change can:

- Pass `test-unit` (which uses the `.[dev,cloud]` profile, no
  schemathesis).
- Fail `contract` (which uses `.[dev,cloud,contract]` and pulls
  schemathesis).
- **Not even run Contract Tests on the deps-only commit**, so branch
  protection picks up the previous (now stale) Contract Tests result.

I shipped session 16 thinking five workflows green meant green. It
did not. The cascade left a real resolver clash that surfaced only when
the next code-path commit re-triggered Contract Tests.

**Always check Contract Tests too. If a pyproject.toml change does not
trigger it, run `gh workflow run contract.yml --ref main` manually
before claiming done.**

### 2. Dependabot cascades have transitive-conflict risk

Each Dependabot PR's CI checks the constraint cluster as it would
look **if only that PR landed**. When you merge seven PRs in
sequence, the cumulative constraint cluster can be unsolvable even
though each individual PR's CI was green.

Concrete example from session 16:

- `#13` bumped schemathesis 4.10 → 4.19. 4.19 requires `pytest>=9`.
- `#22` bumped the pytest spec from `<9` to `<10` — required to even
  install schemathesis 4.19.
- `pytest-asyncio>=0.24,<1` already pinned pytest at `<9`.

Each PR was green in isolation. The merged state was not.

**Mitigation**: when merging a cascade, after every ~3 merges,
manually verify the `contract` and `test-integration` extras still
resolve locally before continuing.

### 3. Memory's "open out-of-scope" list goes stale

The audit-followup section in
`~/.claude/projects/D--/memory/project_de_project.md` listed
`OTEL real instrumentation wiring` and `SLSA provenance` as open. Both
were already closed when I checked — `src/serving/api/telemetry.py`
wires `FastAPIInstrumentor` and `HTTPXClientInstrumentor`, and v1.3.0
artifacts have PEP 740 attestations on PyPI plus
`predicateType: slsa.dev/provenance/v1` on npm.

**Mitigation**: verify before recommending from memory (see the
"Before recommending from memory" section in `~/.claude/CLAUDE.md`).

### 4. `workflow_dispatch` runs do NOT attach as PR status checks

`contract.yml` path filter excludes `.github/workflows/**`, Terraform,
sdk-ts, and `Dockerfile.api` — so for actions-only / sdk-ts-only PRs
the required `contract` check is absent and the PR sits in `BLOCKED`
state forever. The natural reflex from session 17 (run
`gh workflow run contract.yml --ref <branch>`) executes the test
suite green, but the resulting run is event=`workflow_dispatch`, and
GitHub branch protection only counts `push`/`pull_request`
events against the PR head SHA — so the dispatch run does not
satisfy the requirement.

Session 18 worked around this with `gh pr merge --admin --squash` on
#17, #20, #21, #12 after verifying the dispatched `contract` run was
SUCCESS on the rebased SHA. This is safe **only** because the run
genuinely passed.

**Partial long-term fix landed in session 18**: `contract.yml`
`paths:` now also include `pyproject.toml`, `sdk/pyproject.toml`, and
`.github/workflows/**`. So any deps-only PR (the session 16-17
cascade pattern) and any workflow bump (the #17/#20 pattern) will
trigger `contract` naturally. **Still not covered**:
`infrastructure/terraform/**`, `sdk-ts/**`, `Dockerfile*` — these
were left out because the contract suite is python schemathesis and
does not actually exercise terraform/sdk-ts/Dockerfile, so triggering
it there would burn CI time for no signal. For PRs that touch only
those paths, `gh pr merge --admin --squash` after a manual
`gh workflow run contract.yml --ref <branch>` SUCCESS remains the
documented workaround.

## Where things live

- **Per-session memory**: `~/.claude/projects/D--/memory/project_de_project.md`
  — chronological session log, last entry is session 17.
- **Release status**: `docs/dv2-multi-branch/RELEASE_STATUS.md` —
  live PyPI/npm registry table + re-verify recipe.
- **Operational runbooks (production incidents)**: `docs/runbooks/`.
- **Operational runbook (local dev)**: `docs/runbook.md` (singular).
- **CDC production decision record**: `docs/operations/cdc-production-onboarding.md`.
- **Performance baseline**: `docs/perf/ci-hardware-gap-2026-05-24.md`.
- **DV2 work**: `docs/dv2-multi-branch/`, `warehouse/agentflow/dv2/`,
  `infrastructure/dv2/`.
- **Lessons learned doc**: `docs/lessons/ci-repair-sprint-2026-04.md`.

## Quick health commands

```powershell
# Verify all six workflows on HEAD
gh run list --branch main --limit 12 --json status,conclusion,workflowName,headSha | python -c "import sys,json; runs=json.load(sys.stdin); seen=set(); [print(f\"{r['conclusion'] or r['status']:11s} {r['workflowName']}\") for r in runs if r['workflowName'] in ('CI','Security Scan','Load Test','E2E Tests','Staging Deploy','Contract Tests') and not (r['workflowName'] in seen or seen.add(r['workflowName']))]"

# Open Dependabot PRs with merge state
gh pr list --state open --limit 15 --json number,title,mergeable,mergeStateStatus

# Smoke contract resolver locally
python -m pip install --dry-run -e ".[dev,cloud,contract]" 2>&1 | Select-Object -Last 20

# Run broad local no-Docker pytest
$env:SKIP_DOCKER_TESTS='1'
python -m pytest -p no:schemathesis
Remove-Item Env:\SKIP_DOCKER_TESTS
```
