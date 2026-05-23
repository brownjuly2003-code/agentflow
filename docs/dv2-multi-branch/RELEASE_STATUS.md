# Release status — v1.2.0 PUBLISHED

**Status (verified 2026-05-23 via live registry queries):** both v1.1.0
and v1.2.0 are published on all three registries. v1.2.0 ships the
DV2.0 multi-branch demo, per-branch CDC fan-out, audit-follow-up
auth/security hardening, and SDK surface expansion.

## Live registry state

| Registry | Package | Version | Upload time (UTC) | Tag commit |
|----------|---------|---------|-------------------|------------|
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/1.2.0/) | 1.2.0 | 2026-05-23 12:25 | `eb59508` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/1.2.0/)   | 1.2.0 | 2026-05-23 12:25 | `eb59508` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/1.2.0) | 1.2.0 | 2026-05-23 12:25 | `eb59508` |
| PyPI     | [`agentflow-runtime`](https://pypi.org/project/agentflow-runtime/1.1.0/) | 1.1.0 | 2026-04-29 09:07 | `2c72387` |
| PyPI     | [`agentflow-client`](https://pypi.org/project/agentflow-client/1.1.0/)   | 1.1.0 | 2026-04-29 09:07 | `2c72387` |
| npm      | [`@yuliaedomskikh/agentflow-client`](https://www.npmjs.com/package/@yuliaedomskikh/agentflow-client/v/1.1.0) | 1.1.0 | 2026-05-01 03:42 | `2c72387` |

## Re-verify

```bash
# PyPI metadata
curl -sf "https://pypi.org/pypi/agentflow-runtime/1.2.0/json" -o /dev/null && echo OK
curl -sf "https://pypi.org/pypi/agentflow-client/1.2.0/json"  -o /dev/null && echo OK

# npm metadata
npm view "@yuliaedomskikh/agentflow-client@1.2.0" version dist.tarball

# Install smoke
python -m venv /tmp/.afcheck && . /tmp/.afcheck/bin/activate
pip install agentflow-runtime==1.2.0 agentflow-client==1.2.0
python -c "from importlib.metadata import version; print(version('agentflow-runtime'), version('agentflow-client'))"
```

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

Tag `v1.2.0` on commit `eb59508` triggered both
[`publish-pypi.yml`](../../.github/workflows/publish-pypi.yml) (OIDC
Trusted Publishing, no token) and
[`publish-npm.yml`](../../.github/workflows/publish-npm.yml) (npm
Trusted Publishing, OIDC, npm CLI ≥ 11.5.1, no `NPM_TOKEN`). Both
runs completed `success` on 2026-05-23T12:25Z. Re-running them is
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

The next release (1.3.0 or 2.0.0) should follow the same recipe:
bump 5 files (root `pyproject.toml`, `sdk/pyproject.toml`,
`sdk/agentflow/__init__.py`, `sdk-ts/package.json`,
`sdk-ts/package-lock.json`), update the two version assertions in
`tests/unit/test_version.py` and
`tests/unit/test_sdk_backwards_compat.py`, move the `## [Unreleased]`
block to a dated heading in `CHANGELOG.md`, commit, tag, push tag.
Trusted Publishers + OIDC do the rest.
