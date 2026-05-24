# Release status — v1.4.0 PUBLISHED

**Status (verified 2026-05-25 via live registry queries):** v1.1.0,
v1.2.0, v1.3.0, and v1.4.0 are all published on the three registries.
v1.4.0 is a maintenance release bundling documentation
(`docs/SESSION_HANDOFF.md`, `docs/runbooks/` on-call playbooks,
`SECURITY.md`, issue/PR templates), CI hardening (`contract.yml`
paths broadening, `dora.yml` ref fix), repo hygiene
(`.github/dependabot.yml` + `.editorconfig`, auto-merge enabled),
type-stub adoption (`types-PyYAML` + `types-redis` → 18 import-untyped
ignores retired), and the Dependabot Tier A wave 2 dependency bumps
(`mypy<3`, `terraform-aws~>6.46`, `typescript6`, `github-script v9`,
`download-artifact v8`, `build-push v7`, `vitest4`). Two
intentionally-deferred Dependabot PRs were closed as
`wait-for-upstream`: `#23 apache-flink 2.x` (Flink 2.2 Kafka
connector unavailable) and `#11 python 3.14-slim` (docker-not-in-CI
gate). No runtime API changes from v1.3.0.

## Live registry state

| Registry | Package | Version | Upload time (UTC) | Tag commit |
|----------|---------|---------|-------------------|------------|
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

## Re-verify

```bash
# PyPI metadata
curl -sf "https://pypi.org/pypi/agentflow-runtime/1.3.0/json" -o /dev/null && echo OK
curl -sf "https://pypi.org/pypi/agentflow-client/1.3.0/json"  -o /dev/null && echo OK

# npm metadata
npm view "@yuliaedomskikh/agentflow-client@1.3.0" version dist.tarball

# Install smoke
python -m venv /tmp/.afcheck && . /tmp/.afcheck/bin/activate
pip install agentflow-runtime==1.3.0 agentflow-client==1.3.0
python -c "from importlib.metadata import version; print(version('agentflow-runtime'), version('agentflow-client'))"
```

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
- **Audit follow-up sprint** (Codex p1–p9 + Opus 8.2/10): tenant
  isolation across the control plane, SQL guard centralization in
  `nl_queries._prepare_nl_sql()`, entity allowlist enforcement, auth
  fail-closed + entropy + scopes, NetworkPolicy + PodDisruptionBudget
  + securityContext (off-by-default), Helm values JSON schema contract
  + live validation on kind.
- **SDK alignment** (Codex p8 F1–F10): `api_version=` + capture of
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

Tag `v1.3.0` on commit `8fa99e6` triggered both
[`publish-pypi.yml`](../../.github/workflows/publish-pypi.yml) (OIDC
Trusted Publishing, no token) and
[`publish-npm.yml`](../../.github/workflows/publish-npm.yml) (npm
Trusted Publishing, OIDC, npm CLI ≥ 11.5.1, no `NPM_TOKEN`). Both
runs completed `success` on 2026-05-23T23:12Z. Re-running them is
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

The next release (1.4.0 or 2.0.0) should follow the same recipe:
bump 5 files (root `pyproject.toml`, `sdk/pyproject.toml`,
`sdk/agentflow/__init__.py`, `sdk-ts/package.json`,
`sdk-ts/package-lock.json`), update the two version assertions in
`tests/unit/test_version.py` and
`tests/unit/test_sdk_backwards_compat.py`, move the `## [Unreleased]`
block to a dated heading in `CHANGELOG.md`, commit, tag, push tag.
Trusted Publishers + OIDC do the rest.
