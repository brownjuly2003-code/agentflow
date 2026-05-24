# AgentFlow — Session Handoff

**Last updated:** 2026-05-24 (session 19 — A02 verify + Dependabot deferred-PR closure)
**HEAD:** `3d9e9e8` on `main` (drop stale A02 protocol-mixin expansion item; next commit will refresh this line)
**Released:** `v1.3.0` live on PyPI (`agentflow-runtime`, `agentflow-client`)
and npm (`@yuliaedomskikh/agentflow-client`) since 2026-05-23.

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

**All six Tier A Dependabot PRs landed in session 18** (#24 mypy,
#8 terraform-aws, #10 typescript, #17 github-script, #20
download-artifact, #21 docker/build-push, #12 vitest). Resolver
smoke (`pip install --dry-run -e ".[dev,cloud,contract]"`) green on
HEAD `2333104`. See "Recent activity" below for SHAs.

**Two Dependabot PRs closed as `wait-for-upstream`** — neither is
mergeable without external/upstream movement that this repo can't
trigger:

| PR | Bump | Close reason + re-open condition |
|----|------|--------------------------------|
| `#23` (closed) | `apache-flink` 1.19.1 → 2.2.1 (`flink` extra) | Apache docs explicitly state "There is no SQL jar (yet) available for Flink version 2.2" / "There is no connector (yet) available for Flink version 2.2" (https://nightlies.apache.org/flink/flink-docs-release-2.2/docs/connectors/datastream/kafka/). The `[flink]` extra exists to power `src/processing/flink_jobs/{stream_processor,session_aggregator}.py`, both of which depend on `pyflink.datastream.connectors.kafka` + the bundled `flink-sql-connector-kafka` JAR. Merging would ship a non-functional extra. **Re-open when**: `flink-sql-connector-kafka` releases a `-2.x` suffix JAR on Maven Central. **Flink 2.0 API changes already mapped** (in the PR close comment + session memory): `ExternalizedCheckpointCleanup` → `ExternalizedCheckpointRetention` (`pyflink.datastream.externalized_checkpoint_retention`, used via `set_externalized_checkpoint_retention()` instead of `enable_externalized_checkpoints()`), `pyflink.common.time.Time` removed (use `Duration.of_millis()` — already imported in `Dockerfile:35`), Scala 2.12 dropped in 2.0 (bump `SCALA_VERSION=2.12` → `2.13` in `Dockerfile:4`). Code-prep is ~half a day once the connector unblocks |
| `#11` (closed) | `python` 3.11-slim → 3.14-slim (`Dockerfile.api`) | Docker build is not exercised by any required CI workflow (`container-attestation.yml` is `workflow_dispatch`-only), so a broken `docker build` would land silently; ecosystem compat is uneven (`apache-flink`, `dagster`, `langchain-core` have spotty 3.14 wheel coverage, and `slim-bookworm` lacks gcc so source-build fallback fails). **Re-open when**: either `container-attestation.yml` becomes a required check on `pull_request` events OR all heavy extras (`[flink]`, `[ml]`) have published 3.14 wheels on PyPI |

### Tier B — externally user-gated (cannot be unblocked from inside the repo)

| Gate | What is missing | Where the runbook lives |
|------|-----------------|-------------------------|
| **A04** prod CDC source onboarding | Source DB hostnames, credentials, table allowlist, network path, secret-owner / monitoring-owner / rollback-owner assignment | `docs/operations/cdc-production-onboarding.md` § Required Decision Record |
| **A05** prod K8s cluster access | Real cluster context (EKS/GKE/AKS); the test harness already honours external `KUBECONFIG` via `AGENTFLOW_LIVE_REUSE_CLUSTER=1` | `tests/integration/test_helm_values_live_validation.py` (parametrized across `helm/agentflow` + `helm/kafka-connect`) |
| **A03** CI hardware-gap | Decision on paid larger GHA runner or self-hosted; local p99 already at 167 ms target | `docs/perf/ci-hardware-gap-2026-05-24.md` § Alternatives ledger |

These need inputs from outside this repo — credentials, cloud
accounts, budget. No autonomous unblock available; tools cannot
substitute for them.

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
  - Run `terraform init -upgrade` in `infrastructure/terraform/` to
    bump `.terraform.lock.hcl` from the pinned `5.100.0` to the v6
    range now allowed in `main.tf:7`. The TF code itself is already
    v6-compatible — MSK uses the modern `storage_info / ebs_storage_info`
    nested block, S3 uses the modular `aws_s3_bucket_versioning /
    aws_s3_bucket_lifecycle_configuration` / etc. siblings (not the
    deprecated inline blocks), `aws_iam_policy_document` data sources
    do not set the removed `version` attribute, and there are no
    `aws_s3_bucket_object` references — but the lockfile bump itself
    needs a Terraform CLI available, which the local dev env did not
    have during session 18g. Session 18g P2.

- **Before pushing a new `agentflow-api` container image to production
  (currently `container-attestation.yml` is `workflow_dispatch` only):**
  - Run the workflow with `mode=build-and-sign` end-to-end as a
    behavioural smoke on `docker/build-push-action@v7`. Session 18h
    extended the unit test to assert the build step's `id`, `context`,
    `file`, `push`, and both `tags` shape (so v7 schema changes that
    rename or retype those inputs would now fail
    `test_container_attestation_workflow_builds_and_pushes_ghcr_image`),
    but a real Docker build is still the only path that exercises v7
    runtime defaults like `provenance` and `attestations`.

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

- Cut **`v1.4.0`** when there are real feature changes worth releasing.
  The release runbook is `docs/dv2-multi-branch/RELEASE_STATUS.md` §
  "Next release recipe". `[Unreleased]` in `CHANGELOG.md` already has
  five entries queued (runbooks + README + helm + SDK + SECURITY +
  Dependabot/.editorconfig + hotfix) so the changelog body is already
  written.
- **OTEL observability backfill** — wiring is in
  `src/serving/api/telemetry.py`; downstream Grafana panels referenced
  in `docs/runbooks/api-5xx-spike.md` need to be authored in
  `infrastructure/observability/` once a real Prometheus stack exists.
- **OneScreen / proof-pack-tier polish** lives in separate repos; the
  `docs/codex-tasks/` ledger has historical follow-ups if appetite
  appears for cross-cutting cleanup.

## Recent activity — sessions 11 → 17 compressed

All seven sessions shipped to `main` between 2026-05-24 evening and
2026-05-24 night.

| Session | SHAs | Theme |
|---------|------|-------|
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
| **19** | `3d9e9e8` + this commit | (1) Verified A02 protocol-mixin expansion factually complete (0 `[attr-defined]` ignores in `src/`, `disable_error_code` gone from `pyproject.toml`, `mypy src` clean on 96 files) → dropped stale Tier C bullet. (2) Closed both intentionally-deferred Dependabot PRs (#23 apache-flink 2.x, #11 python 3.14-slim) as `wait-for-upstream` after surfacing the Flink-2.2 Kafka-connector gap (Apache docs confirm no `flink-sql-connector-kafka` 2.x JAR yet — merging #23 would ship a non-functional `[flink]` extra). Flink 2.0 API breakage map (`ExternalizedCheckpointCleanup` → `ExternalizedCheckpointRetention`, `pyflink.common.time.Time` removed, Scala 2.12 dropped) preserved in PR close comments + this handoff for the eventual re-bump |

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
