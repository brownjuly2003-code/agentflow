# Dependency compatibility remediation — 2026-07-30

## Scope

This record covers the Python cloud/Iceberg and optional MCP dependency
boundaries discovered by the final CI run. It does not claim production
acceptance or replace the remaining live golden-topology gates.

After the owner asked to preserve the remaining Grok/Grokw weekly quota, Codex
performed all diagnosis, remediation, Mac verification, documentation, and Git
closeout work described here. Grok was not invoked for this remediation.

## Trigger

GitHub Actions CI run
[`30573486366`](https://github.com/brownjuly2003-code/agentflow/actions/runs/30573486366)
tested commit `f11fd59fea61fc7bf29d3fa8f8c41139c236cfb4`. Its lint,
lock, SDK, Terraform, schema, Helm, and Python 3.11/3.12/3.13 compatibility
gates passed. Separate Contract, E2E, Flink Smoke, Load, Security Scan,
Scorecard, and Staging Deploy workflows also passed.

Two dependency boundaries still failed:

- the integration job resolved `pyiceberg==0.11.1` without
  `pyiceberg-core`; five Iceberg write/materialization tests raised
  `NotInstalledError`;
- `integrations[mcp]` allowed an unbounded major upgrade, so the unit job
  resolved `mcp==2.0.0`; that release removed the MCP 1.x `Tool.inputSchema`
  model field and low-level `Server.list_tools()` decorator used by the
  integration.

## Remediation

The cloud extra now installs:

```toml
"pyiceberg>=0.7,<1",
"pyiceberg-core>=0.7,<0.8",
```

PyIceberg 0.11 uses the native package for partition transforms and table
appends. The previously selected core 0.8 distribution excludes Python 3.13;
core 0.7 provides a stable-ABI wheel across the supported Python 3.11–3.13
matrix. `uv.lock` and the hash-locked Docker export both resolve
`pyiceberg-core==0.7.0`.

The MCP extra now declares `mcp>=1.0,<2`. This preserves the integration's
documented MCP 1.x API instead of silently accepting a breaking major release.
A unit dependency contract pins both boundaries so future configuration or
lock drift fails before the runtime jobs.

## Verification

- RED contract stage: two new dependency contracts failed against the old
  declarations.
- GREEN targeted stage: `38 passed` locally across dependency contracts, MCP,
  and non-Docker Iceberg scenarios.
- Full Windows Python 3.13 unit/property suite: `2170 passed, 1 warning`.
- `uv 0.8.23`: `uv lock --check` passed; the generated lock/export diff adds
  only `pyiceberg-core==0.7.0`.
- Isolated Mac clone:
  `/tmp/agentflow-ci-f11-codex-deps-01`, based on exact `f11fd59` plus the
  five candidate dependency files.
- Clean Mac Python 3.13 environment:
  `mcp==1.29.0`, `pyiceberg==0.11.1`,
  `pyiceberg-core==0.7.0`, and `pip check` passed.
- Mac contract/MCP/Iceberg selection: all `39` tests passed, including the
  Docker REST-catalog materialization case.
- Direct OSV queries for the three resolved packages returned no vulnerability
  records.

The changed Docker lock was also rebuilt through `Dockerfile.api` on Mac:

```text
agentflow-api:security-codex-f11deps-01
manifest list sha256:95254620bf98e73ce89feae28e0b178a3cf00956c7e63eedd40f8958705645d1
```

The build installed `pyiceberg-core==0.7.0`, completed `pip check`, and then
removed `pip`, `setuptools`, and `wheel`. Runtime API import returned
`AgentFlow Query API`; `python -m pip` remained absent. Trivy `0.70.0` with
`HIGH,CRITICAL`, `--ignore-unfixed`, and `--exit-code 1` exited `0`; every
reported OS and Python package row was clean.

## Evidence boundary

This is local and isolated-Mac acceptance of the dependency candidate. The
exact pushed source state must still complete the repository's GitHub CI and
Security Scan. Published-image signing, external penetration testing, live
lake-to-serving materialization, restore/replay, and soak/rollback remain
separate gates.
