# AgentFlow — Session Handoff

**Last updated:** 2026-05-24
**HEAD:** `c90511b` on `main` (post-Dependabot-cascade hotfix)
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

**Six Dependabot PRs waiting for review.** All from 2026-05-24, all
have only `dora-report` (non-required) failing for environmental
reasons. Pre-merge required-check status is mixed — see notes.

| PR | Bump | Risk | Pre-merge action |
|----|------|------|------------------|
| `#10` | `typescript` 5.9.3 → 6.0.3 (`sdk-ts/`) | TS major, strict-mode changes | Run `cd sdk-ts && npm run typecheck && npm test` against the PR branch first |
| `#12` | `vitest` 3.2.4 → 4.1.7 (`sdk-ts/`) | test-framework major | Same — `npm test` against the PR branch |
| `#17` | `actions/github-script` v7 → v9 | CI scripting major | After rebase, verify `Contract Tests` and any `actions/github-script` consumers still work (chaos.yml uses it for issue creation) |
| `#20` | `actions/download-artifact` v4 → v8 | Major bump, four versions | Risk of artifact path changes; check all `download-artifact` invocations in workflows |
| `#21` | `docker/build-push-action` v6 → v7 | CI action major | Verify `container-attestation.yml` still builds cleanly via `workflow_dispatch` smoke |
| `#8`  | `hashicorp/aws` `~> 5.60` → `~> 6.46` (Terraform) | Provider major, breaking attr changes | CI `terraform-validate` will catch most; merge only after green check on rebased PR |

**Two Dependabot PRs intentionally deferred** — they break paths CI
does not cover:

| PR | Bump | Why deferred |
|----|------|--------------|
| `#23` | `apache-flink` 1.19.1 → 2.2.1 (`flink` extra) | `pyflink.datastream` imports in `src/processing/flink_jobs/` use Flink 1.x API. CI does not install the `[flink]` extra, so a silent regression would ship to downstream users. Needs a Flink 2.x compat sweep before merge |
| `#11` | `python` 3.11-slim → 3.14-slim (`Dockerfile.api`) | Python 3.14 was released 2026-10; library compat is uneven. Docker build is not part of CI (`container-attestation.yml` is `workflow_dispatch`), so a broken `docker build` would not surface. Defer until the 3.14 ecosystem settles |

### Tier B — externally user-gated (cannot be unblocked from inside the repo)

| Gate | What is missing | Where the runbook lives |
|------|-----------------|-------------------------|
| **A04** prod CDC source onboarding | Source DB hostnames, credentials, table allowlist, network path, secret-owner / monitoring-owner / rollback-owner assignment | `docs/operations/cdc-production-onboarding.md` § Required Decision Record |
| **A05** prod K8s cluster access | Real cluster context (EKS/GKE/AKS); the test harness already honours external `KUBECONFIG` via `AGENTFLOW_LIVE_REUSE_CLUSTER=1` | `tests/integration/test_helm_values_live_validation.py` (parametrized across `helm/agentflow` + `helm/kafka-connect`) |
| **A03** CI hardware-gap | Decision on paid larger GHA runner or self-hosted; local p99 already at 167 ms target | `docs/perf/ci-hardware-gap-2026-05-24.md` § Alternatives ledger |

These need inputs from outside this repo — credentials, cloud
accounts, budget. No autonomous unblock available; tools cannot
substitute for them.

### Tier C — forward backlog (when there is bandwidth)

- Cut **`v1.4.0`** when there are real feature changes worth releasing.
  The release runbook is `docs/dv2-multi-branch/RELEASE_STATUS.md` §
  "Next release recipe". `[Unreleased]` in `CHANGELOG.md` already has
  five entries queued (runbooks + README + helm + SDK + SECURITY +
  Dependabot/.editorconfig + hotfix) so the changelog body is already
  written.
- **Protocol-mixin expansion (A02)** to remaining `attr-defined`
  override paths beyond `src/serving/semantic_layer/query/` and
  `sdk/agentflow/retry.py`.
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

## Lessons (recent, load-bearing)

These are the calluses from sessions 16–17 specifically — keep them
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
