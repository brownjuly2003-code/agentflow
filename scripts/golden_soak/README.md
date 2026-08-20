# Golden 4-hour soak source pack

This directory tracks the eight byte-exact files from source identity
`20260819-07`. `MANIFEST.json` records their provenance, byte sizes, and
SHA-256 digests. The files are a source reference only; their Kubernetes job
manifests are not a Docker Compose runtime contract.

The current architecture verdict and finding register are documented in
[`ci-soak-r1-r7-architecture-audit.md`](../../ci-soak-r1-r7-architecture-audit.md).
The exact local verification evidence and authoritative next-session resume
checkpoint are in
[`ci-soak-runtime-harness.md`](../../ci-soak-runtime-harness.md). The older
[`ci-soak-compose-foundation.md`](../../docs/operations/ci-soak-compose-foundation.md)
is historical topology context, not current resume state.

The root Compose overlay is a **separate capacity-independent**
traffic/exactness/Flink-quiet gate. It **does not close** the Mac
kind/operator/HA/rollback golden-soak gate.

This directory now also contains a local runtime controller (`runtime.py`) and
an identity-bound Kubernetes-pods compatibility shim (`pods_shim.py`). The
controller validates every manifest size and SHA-256 before its first Docker
command, uses the eight pack files through read-only mounts, requires one
stable JobManager and one stable TaskManager, and writes fail-closed evidence
before project-scoped cleanup.

The immutable source pack and Compose configuration by themselves **cannot emit a soak PASS**.
Unit tests and configuration validation are not runtime evidence. There is
still no CI workflow, and this implementation has not been rehearsed against
live containers in the repository handoff that introduced it.

Validate only the merged Compose model with:

```powershell
docker compose -f docker-compose.yml -f docker-compose.flink.yml -f docker-compose.soak.yml config --quiet
```

Do not infer a runtime PASS from successful configuration validation.

## Local controller

The later, separately authorized rehearsal slice can use a fresh output
directory and a dedicated Compose project name:

```powershell
python scripts/golden_soak/runtime.py `
  --project-name agentflow-ci-soak-rehearsal `
  --output-dir .artifacts/soak-rehearsal `
  --count 2000
```

That command starts and later removes only the named Compose project, including
its volumes. It always stops the observer, captures bounded logs, removes the
transient shim/observer containers, and runs scoped `compose down -v` in its
cleanup path. Before build/up it refuses any existing container, volume, or
network carrying that Compose project label, so cleanup cannot adopt an older
project. Reuse of a non-empty output directory is also rejected.

Counts below `1440000` can emit only `RESULT=REHEARSAL_PASS`; they cannot emit
the full-soak token. The default `1440000 @ 100 eps` path may emit
`RESULT=SOAK_PASS_DUAL_MEAN_90` only after producer, observer, exactness,
Flink-identity, zero-restart, and cleanup checks all pass. Even that result is
the **separate capacity-independent** gate and **does not close** the Mac
kind/operator/HA/Helm-rollback gate.
