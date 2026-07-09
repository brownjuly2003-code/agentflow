# Release status — v2.0.0 PUBLISHED

**Status (verified 2026-07-06 via live registry queries):** v1.1.0
through v2.0.0 are all published on the three registries (PyPI
`agentflow-runtime` + `agentflow-client`, npm
`@yuliaedomskikh/agentflow-client`). v2.0.0 is the major release that
re-founds the demo universe and ships the scale path: the business
legend re-pinned end-to-end to an own-brand kitchen-appliance importer
in ₽ (breaking for the retired fashion-retail/USD surfaces), the
external real-retailer dataset removed outright (breaking: loader
deleted, its at-scale benchmark retired as historical), the control
plane externalized to PostgreSQL behind the `ControlPlaneStore` port
(ADR 0010, slices 1–6 incl. the Helm scale profile), three operational
read surfaces split out of the agent catalog (ADR 0011), the three-node
demo topology implemented and deployed to HF Spaces (ADR 0012 — see
"Live demo surfaces" below for which nodes are awake), and the G2 audit
closure (spec/seed consistency, journal-scan hardening, live evidence
re-captures, demo serving-backend pin).

v1.6.0 was the architecture-fixing release: ClickHouse became the
shipped serving engine (ADR 0006 Phase 1), PII protection moved to
engine-enforced vault governance (ADR 0006 Phase 2), plus the vendored
NL→SQL generation engine (ADR 0008), the DV2 raw vault PostgreSQL
migration, the MinIO-backed PyIceberg catalog, and the OpenSSF
Scorecard channel (5.8 → 7.0).

## Live registry state

| Registry | Package | Version | Upload time (UTC) | Tag commit |
|----------|---------|---------|-------------------|------------|
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/2.0.0/) | 2.0.0 | 2026-07-06 16:23 | `a47d000` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/2.0.0/)   | 2.0.0 | 2026-07-06 16:23 | `a47d000` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/2.0.0) | 2.0.0 | 2026-07-06 16:23 | `a47d000` |
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/1.6.0/) | 1.6.0 | 2026-07-02 00:55 | `734132a` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/1.6.0/)   | 1.6.0 | 2026-07-02 00:55 | `734132a` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/1.6.0) | 1.6.0 | 2026-07-02 00:55 | `734132a` |
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/1.5.0/) | 1.5.0 | 2026-06-05 07:48 | `c99d094` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/1.5.0/)   | 1.5.0 | 2026-06-05 07:48 | `c99d094` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/1.5.0) | 1.5.0 | 2026-06-05 07:48 | `c99d094` |
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/1.4.0/) | 1.4.0 | 2026-05-24 21:05 | `e58693b` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/1.4.0/)   | 1.4.0 | 2026-05-24 21:05 | `e58693b` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/1.4.0) | 1.4.0 | 2026-05-24 21:05 | `e58693b` |
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/1.3.0/) | 1.3.0 | 2026-05-23 23:12 | `8fa99e6` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/1.3.0/)   | 1.3.0 | 2026-05-23 23:12 | `8fa99e6` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/1.3.0) | 1.3.0 | 2026-05-23 23:12 | `8fa99e6` |
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/1.2.0/) | 1.2.0 | 2026-05-23 12:25 | `eb59508` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/1.2.0/)   | 1.2.0 | 2026-05-23 12:25 | `eb59508` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/1.2.0) | 1.2.0 | 2026-05-23 12:25 | `eb59508` |
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/1.1.0/) | 1.1.0 | 2026-04-29 09:07 | `2c72387` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/1.1.0/)   | 1.1.0 | 2026-04-29 09:07 | `2c72387` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/1.1.0) | 1.1.0 | 2026-05-01 03:42 | `2c72387` |

## Live demo surfaces

Four Docker Spaces exist under `liovina`, all built from the same image.
The free tier caps how many `cpu-basic` Spaces one account may run at once;
that cap is currently reached by **four** running Spaces on this account, two of
which serve other projects. `POST .../restart` on a paused Space is refused
outright (`403`, "you've reached your cpu-basic quota limit"), and a second
account is not a way around it — creating an additional free Docker Space is
refused too (`POST /api/repos/create` → `402`; only static Spaces are free).

So the three-node topology is deployed but not fully awake. A paused Space
answers `503` until a running one is paused to make room; nothing about the
deployment is missing, only the concurrent-compute quota.

| Space | Role | Runtime stage | `/v1/health` |
|-------|------|---------------|--------------|
| [`agentflow-center`](https://liovina-agentflow-center.hf.space) | center hub (ADR 0012) | RUNNING | `200` |
| [`agentflow-edge-spb`](https://liovina-agentflow-edge-spb.hf.space) | edge branch `spb` | RUNNING | `200` |
| [`agentflow-edge-ekb`](https://liovina-agentflow-edge-ekb.hf.space) | edge branch `ekb` | PAUSED | `503` |
| [`agentflow-demo`](https://liovina-agentflow-demo.hf.space) | standalone demo | PAUSED | `503` |

Probed 2026-07-09 (`GET /v1/health` + `GET /api/spaces/liovina/{name}`; the two
quota errors above were reproduced the same day).
The cross-node evidence ("Verify live" in `deploy/hf-space/three-node/DEPLOY.md`)
was captured on 2026-07-06 while `ekb` was awake.

## GitHub Releases note

`gh release list` reports GitHub Release objects for every tag through
`v1.6.0`. The `v1.2.0`, `v1.3.0`, and `v1.4.0` Release objects were created on
2026-06-03, and the `v1.5.0` object was backfilled on 2026-07-02 alongside the
`v1.6.0` release, all from the existing tags to close the provenance gap with
the package registries. Backfills are metadata only — no re-publish: the
PyPI/npm artifacts and Trusted Publishing runs predate those Release objects
and remain the package source of truth (the publish workflows trigger on tag
push, not on `release`). GitHub Releases and the PyPI/npm registries are now
consistent through `v2.0.0`, with `v2.0.0` marked Latest (created 2026-07-06
alongside the tag; no backfills were needed this cycle).

## Re-verify

```bash
# PyPI metadata
curl -sf "https://pypi.org/pypi/agentflow-runtime/2.0.0/json" -o /dev/null && echo OK
curl -sf "https://pypi.org/pypi/agentflow-client/2.0.0/json"  -o /dev/null && echo OK

# npm metadata
npm view "@yuliaedomskikh/agentflow-client@2.0.0" version dist.tarball

# Install smoke
python -m venv /tmp/.afcheck && . /tmp/.afcheck/bin/activate
pip install agentflow-runtime==2.0.0 agentflow-client==2.0.0
python -c "from importlib.metadata import version; print(version('agentflow-runtime'), version('agentflow-client'))"
```

## What's in v1.4.0 vs v1.3.0

`git log --oneline 8fa99e6..e58693b` shows the changes. The high-level shape:

- **Public repo and release docs:** refreshed README/release status,
  on-call runbooks, `SECURITY.md`, issue/PR templates, and release
  rollback guidance.
- **CI and repo hygiene:** `contract.yml` trigger broadening, DORA workflow
  ref hardening, Dependabot configuration, `.editorconfig`, and auto-merge
  readiness documentation.
- **Type and dependency maintenance:** `types-PyYAML` and `types-redis`
  adoption, `mypy<3`, Terraform AWS provider `~> 6.46`, TypeScript 6,
  GitHub Actions major bumps, and Vitest 4. Two Dependabot PRs remain closed
  as `wait-for-upstream`: Flink 2.x Kafka connector availability and Python
  3.14 Docker build coverage.
- **Runtime compatibility:** no runtime API changes from `v1.3.0`.

## What's in v1.3.0 vs v1.2.0

`git log --oneline eb59508..8fa99e6` shows the changes. The high-level shape:

- **A04 chart hardening** (`helm/kafka-connect/`): NetworkPolicy +
  PodDisruptionBudget + pod/container securityContext + `/tmp` memory
  emptyDir. `values.schema.json` requires all five new top-level keys;
  defaults are off-by-default for backwards compatibility on existing
  clusters. See `docs/operations/cdc-production-onboarding.md` § Chart
  hardening baseline for production switch-on recommendations.
- **A05 live-validation expansion**: `test_helm_values_live_validation.py`
  now parametrized across both `helm/agentflow` and `helm/kafka-connect`,
  with a `ChartCase` dataclass per chart. `conftest.kind_cluster`
  honours `AGENTFLOW_LIVE_REUSE_CLUSTER=1` so the schema gate can run
  against an external managed cluster (EKS/GKE/AKS) via just
  `KUBECONFIG=...` instead of provisioning kind.
- **A03 CI hardware-gap acceptance** (`docs/perf/ci-hardware-gap-2026-05-24.md`):
  Load Test gates raised to 1.3x the 2026-04-25 CI baseline (entity
  GETs 750 → 900 ms, product/metrics 900 → 1100 ms, POST query/batch
  1000 → 1200 ms). Local SLO p99 < 200 ms on the entity endpoint is
  unchanged. The doc tracks msgspec swap, async DuckDB pool, paid
  larger runner, and self-hosted runner as future re-evaluation
  triggers.

## What's in v1.2.0 vs v1.1.0

`git log --oneline 2c72387..eb59508 -- src/ sdk/ sdk-ts/ integrations/`
shows the changes. The high-level shape:

- **DV2.0 multi-branch demo** (`docs/dv2-multi-branch/`,
  `warehouse/agentflow/dv2/`, `infrastructure/dv2/`): Data Vault 2.0
  warehouse on a self-hosted kind cluster (ClickHouse 25.5 + Postgres
  17 + MinIO), 5 branches (MSK / SPB / EKB / DXB / ALA), 3 source
  systems, 3 jurisdictions. Argo Workflows orchestration, dbt mart
  layer, cold-tier S3 offload, MaterializedPostgreSQL CDC (single-DB
  + per-branch fan-out variants), asciinema cast + voice-over MP4 +
  web-UI screencast.
- **Audit follow-up sprint**: tenant
  isolation across the control plane, SQL guard centralization in
  `nl_queries._prepare_nl_sql()`, entity allowlist enforcement, auth
  fail-closed + entropy + scopes, NetworkPolicy + PodDisruptionBudget
  + securityContext (off-by-default), Helm values JSON schema contract
  + live validation on kind.
- **SDK alignment** (F1–F10): `api_version=` + capture of
  `X-AgentFlow-{Version,Latest-Version,Deprecated}` headers, async-
  parity for `contract_version=`, `as_of=` on entity/metric methods,
  `EntityMeta`/`MetricMeta` typed envelopes, 8 new typed public methods
  (`explain_query`, `search`, `list_contracts`, `get_contract`,
  `diff_contracts`, `validate_contract`, `get_lineage`, `get_changelog`),
  `idempotency_key=` on POST methods, `PermissionDeniedError` /
  `CircuitOpenError` exception classes, `py.typed` marker.
- **Performance:** PII masker `Path()` normalization (eliminates a
  Windows path-mismatch rebuild on every request), tenant qualification
  cache (`TenantRouter` + `QueryEngine` instance-level caches). Local
  p99 936 ms → 167 ms (-82%, +103% throughput). CI runner POST p99
  still ~800–1000 ms; tracked for the next perf iteration.

## How the release fired

Tag `v2.0.0` on commit `a47d000` (PR #166, the exact 10-file v1.6.0 cut
pattern) triggered both publish workflows on 2026-07-06; both runs
completed `success` and the packages were visible in the registries at
2026-07-06T16:23Z (verified live). The `test_version` gotcha applied as
documented: `pip install -e ./sdk` re-run before the local gate (full
unit suite, 1670 passed).

Previous cycle: tag `v1.6.0` on commit `734132a` triggered both
[`publish-pypi.yml`](../../.github/workflows/publish-pypi.yml) (OIDC
Trusted Publishing, no token) and
[`publish-npm.yml`](../../.github/workflows/publish-npm.yml) (npm
Trusted Publishing, OIDC, npm CLI ≥ 11.5.1, no `NPM_TOKEN`). Both
runs completed `success` on 2026-07-02, and packages were visible in
the registries at 2026-07-02T00:55Z. Re-running them is
idempotent on the verify step but will fail at the upload step with
`File already exists` — re-tag with a new version, do not retry the
same one.

## Tag state

| Tag        | Commit    | State      |
|------------|-----------|------------|
| v1.0.0     | (release) | published  |
| v1.0.1     | (release) | published  |
| v1.1.0-rc1 | (rc)      | published  |
| v1.1.0     | `2c72387` | published  |
| v1.2.0     | `eb59508` | published  |
| v1.3.0     | `8fa99e6` | published  |
| v1.4.0     | `e58693b` | published  |
| v1.5.0     | `c99d094` | published  |
| v1.6.0     | `734132a` | published  |
| v2.0.0     | `a47d000` | published  |

The next release should follow the same recipe:
bump 5 files (root `pyproject.toml`, `sdk/pyproject.toml`,
`sdk/agentflow/__init__.py`, `sdk-ts/package.json`,
`sdk-ts/package-lock.json`), update Helm chart/app image pins when the
release scope requires it, update the two version assertions in
`tests/unit/test_version.py` and
`tests/unit/test_sdk_backwards_compat.py`, move the `## [Unreleased]`
block to a dated heading in `CHANGELOG.md`, commit, tag, push tag.
Trusted Publishers + OIDC do the rest. Note: `test_version.py` checks
the installed distribution metadata — re-run `pip install -e sdk/`
locally after the bump or the test fails on stale metadata.
