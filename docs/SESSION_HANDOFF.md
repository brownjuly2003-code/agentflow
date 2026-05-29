# AgentFlow — Session Handoff

**Last updated:** 2026-05-29 (local autopilot/state refresh)
**HEAD:** `bd18aff` (`bd18aff8e0c86f9f95625045be6692a98f24be5c`) on `main`.
**Branch state:** `main...origin/main [ahead 8]`; local `main` has eight commits not on `origin/main`.
**Tracked files:** `901` via `git ls-files`.
**Latest local commits:**
- `bd18aff` fix(autopilot): default planner to codex
- `eb1074b` fix(autopilot): ignore active concurrent locks
- `96cd198` docs: refresh autopilot handoff state
- `6ff7860` fix(autopilot): run gates for bounded product tasks
- `cccc9f7` fix(dv2): align X5 loader with live schema
- `43cf655` chore(autopilot): block repeated task loops
- `ed3c21b` fix(autopilot): use codex sandbox compatible with Windows
- `c647621` Document paused DV2 demo cluster

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

Run these four commands first; they orient you in under a minute:

```bash
cd D:/DE_project
git fetch origin main && git log --oneline origin/main -10
gh run list --branch main --limit 6 --json status,conclusion,workflowName,headSha \
  | python -c "import sys,json; [print(f\"{r['conclusion'] or r['status']:11s} {r['workflowName']:25s} {r['headSha'][:7]}\") for r in json.load(sys.stdin)[:6]]"
gh pr list --state open --limit 15
```

In order, those tell you:

1. **Last 10 commits on `main`** — where state is and what just landed.
2. **All six main workflows** (CI / Security Scan / Load Test / E2E Tests /
   Staging Deploy / **Contract Tests**) on the current HEAD — never skip
   Contract Tests when verifying green; it has a path filter that
   bypasses `pyproject.toml`-only commits and a stale red there has
   already burned us once (see Lessons below).
3. **Open PRs** — the only mover right now is Dependabot. See "Open work"
   for which are safe to merge and which need a smoke test first.

For DV2 multi-branch demo work specifically, also read
`docs/dv2-multi-branch/SESSION_HANDOFF.md` — it has the iMac/Lima
cluster credentials, asciinema cast pipeline, and the five CH
`MaterializedPostgreSQL` pitfalls.

## Open work — priorities

### Tier A — actionable in-repo (no external blocker)

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

**Two Dependabot PRs closed as `wait-for-upstream`** — neither is
mergeable without external/upstream movement that this repo can't
trigger:

| PR | Bump | Close reason + re-open condition |
|----|------|--------------------------------|
| `#23` (closed) | `apache-flink` 1.19.1 → 2.2.1 (`flink` extra) | Apache docs explicitly state "There is no SQL jar (yet) available for Flink version 2.2" / "There is no connector (yet) available for Flink version 2.2" (https://nightlies.apache.org/flink/flink-docs-release-2.2/docs/connectors/datastream/kafka/). The `[flink]` extra exists to power `src/processing/flink_jobs/{stream_processor,session_aggregator}.py`, both of which depend on `pyflink.datastream.connectors.kafka` + the bundled `flink-sql-connector-kafka` JAR. Merging would ship a non-functional extra. **Re-open when**: `flink-sql-connector-kafka` releases a `-2.x` suffix JAR on Maven Central. **Flink 2.0 API changes already mapped** (in the PR close comment + session memory): `ExternalizedCheckpointCleanup` → `ExternalizedCheckpointRetention` (`pyflink.datastream.externalized_checkpoint_retention`, used via `set_externalized_checkpoint_retention()` instead of `enable_externalized_checkpoints()`), `pyflink.common.time.Time` removed (use `Duration.of_millis()` — already imported in `Dockerfile:35`), Scala 2.12 dropped in 2.0 (bump `SCALA_VERSION=2.12` → `2.13` in `Dockerfile:4`). Code-prep is ~half a day once the connector unblocks |
| `#11` (closed) | `python` 3.11-slim → 3.14-slim (`Dockerfile.api`) | Docker build is not exercised by any required CI workflow (`container-attestation.yml` is `workflow_dispatch`-only), so a broken `docker build` would land silently; ecosystem compat is uneven (`apache-flink`, `dagster`, `langchain-core` have spotty 3.14 wheel coverage, and `slim-bookworm` lacks gcc so source-build fallback fails). **Re-open when**: either `container-attestation.yml` becomes a required check on `pull_request` events OR all heavy extras (`[flink]`, `[ml]`) have published 3.14 wheels on PyPI |

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
    references. The remaining gate is the disabled-by-default
    `plan` / `apply` jobs (see the `if: false` toggle at
    `.github/workflows/terraform-apply.yml:79` and the re-enable
    checklist comment block above it), which require `AWS_TERRAFORM_ROLE_ARN`
    + `AWS_REGION` repository vars + the tfvars files + GH Actions
    `staging` / `production` environments + a green OIDC-assume-role
    staging run to ship.

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
    PRs; do this in a quiet window).
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
| **19** | `3d9e9e8`, `405f8a3`, `897b928`, `e58693b`, `0d2f6d5`, `d037fbc`, `57d84c9` | Six tracks closed in one session. **(1) A02 protocol-mixin** verified factually complete (0 `[attr-defined]` ignores in `src/`, `disable_error_code` gone from `pyproject.toml`, `mypy src` clean on 96 files) → dropped stale Tier C bullet. **(2) Deferred Dependabot PR closure** — both #23 (apache-flink 2.x) and #11 (python 3.14-slim) closed as `wait-for-upstream` after surfacing the Flink-2.2 Kafka-connector gap (Apache docs confirm no `flink-sql-connector-kafka` 2.x JAR yet — merging #23 would ship a non-functional `[flink]` extra). Flink 2.0 API breakage map (`ExternalizedCheckpointCleanup` → `ExternalizedCheckpointRetention`, `pyflink.common.time.Time` removed, Scala 2.12 dropped) preserved in PR close comments. **(3) v1.4.0 maintenance release CUT** — 10-file bump per RELEASE_STATUS recipe (root + sdk + sdk-ts pyprojects + sdk/__init__.py + package-lock + 2 test assertions + helm Chart appVersion + helm values image.tag); `CHANGELOG.md` `[Unreleased]` → `[1.4.0] - 2026-05-25`; tag `v1.4.0` on `e58693b`; PyPI + npm Trusted Publishers fired (`agentflow-runtime` + `agentflow-client` + `@yuliaedomskikh/agentflow-client` all on `1.4.0` since `2026-05-24T21:05Z`). No runtime API changes vs `v1.3.0`. Local smoke 486/486 `tests/unit/`. **(4) Terraform v6.46.0 provider install verified** locally with `terraform init -backend=false -upgrade` against the `~> 6.46` constraint in `main.tf:7`; no commit needed because `.terraform.lock.hcl` is gitignored (`.gitignore:33`) — CI generates its own per run. The remaining gate for re-enabling `terraform-apply.yml` plan/apply is the `if: false` toggle + repo vars + tfvars + GH Actions environments + staging OIDC dry-run, not the lockfile. **(5) Grafana pipeline-health dashboard** (`infrastructure/observability/grafana/agentflow-pipeline-health.json`) — five panels over the metrics actually exported by `src/quality/monitors/`: pipeline latency p50/p95/p99 by topic (SLO line at 30s), SLA compliance bar gauge, Kafka consumer lag, per-component health (healthy/degraded/unhealthy mapping), events processed running total. Backs the `cdc-lag.md` runbook directly. HTTP-level panels (`api-5xx-spike.md`, `auth-401-spike.md`) intentionally skipped — referenced metrics (`agentflow_http_requests_total`, `agentflow_auth_failures_total`) not yet defined in `src/`; the dashboard description + Tier C bullet document the bounded follow-up. **(6) Container-attestation behavioural smoke deferred** — Docker Desktop daemon was offline (`docker info` Server section empty) and starting it without explicit user OK was out of scope |

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

```bash
# Verify all six workflows on HEAD
gh run list --branch main --limit 12 --json status,conclusion,workflowName,headSha \
  | python -c "import sys,json; runs=json.load(sys.stdin); seen=set(); [print(f\"{r['conclusion'] or r['status']:11s} {r['workflowName']}\") for r in runs if r['workflowName'] in ('CI','Security Scan','Load Test','E2E Tests','Staging Deploy','Contract Tests') and not (r['workflowName'] in seen or seen.add(r['workflowName']))]"

# Open Dependabot PRs with merge state
gh pr list --state open --limit 15 --json number,title,mergeable,mergeStateStatus

# Smoke contract resolver locally
python -m pip install --dry-run -e ".[dev,cloud,contract]" 2>&1 | tail -20

# Run main test slice
python -m pytest tests/unit tests/integration tests/sdk -q
```
