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

## Tracked bootstrap and terminal record

`bootstrap.sh` is the POSIX entry point for the separately authorized wrapper
path. It checks `/usr/local/bin/python3` and then `python3`, requires Python
3.11 or newer, and invokes `wrapper.py` with an exact attempt identity, terminal
result path, and `--plan-path`. The plan is bounded JSON with schema version 2
and these fields:

```json
{
  "schema_version": 2,
  "shared_root": "/Users/julia/agentflow-fc5-7113966",
  "snapshot_path": "/Users/julia/agentflow-fc5-7113966/fresh-snapshot",
  "output_parent_path": "/Users/julia/agentflow-fc5-7113966/fresh-output",
  "owner_lock_path": "/Users/julia/agentflow-fc5-7113966/.ci-soak-owner.lock",
  "source_probe": {
    "command": ["/absolute/path/to/source-daemon-probe", "..."],
    "expected_sha256": "<64 lowercase hex>",
    "cleanup_command": ["/absolute/path/to/source-probe-cleanup-check", "..."]
  },
  "output_probe": {
    "command": ["/absolute/path/to/output-daemon-probe", "..."],
    "expected_sha256": "<64 lowercase hex>",
    "cleanup_command": ["/absolute/path/to/output-probe-cleanup-check", "..."]
  },
  "clickhouse_probes": {
    "container_health": {"command": ["..."], "expected_output": "healthy"},
    "host_route": {"command": ["..."], "expected_output": "1"},
    "workload_route": {"command": ["..."], "expected_output": "1"}
  },
  "stop_command": ["/absolute/path/to/co-tenant-stop", "..."],
  "controller_command": ["python3", "scripts/golden_soak/runtime.py", "..."],
  "controller_result_path": "/Users/julia/agentflow-fc5-7113966/fresh-output/result-final.txt",
  "restore_command": ["/absolute/path/to/restore-command", "..."],
  "kind_restore": {
    "container_id": "<exact 64-character lowercase container ID>",
    "identity_command": ["..."],
    "running_command": ["..."],
    "restart_count_command": ["..."],
    "apiserver_count_command": ["..."],
    "livez_command": ["..."],
    "livez_max_attempts": 60,
    "livez_consecutive_successes": 2
  }
}
```

The bootstrap invocation shape is:

```sh
scripts/golden_soak/bootstrap.sh ATTEMPT_ID WRAPPER_RESULT_PATH \
  --plan-path PLAN_PATH
```

All paths are absolute. The snapshot, output parent, controller result, and
wrapper result must resolve under the declared shared root; the two daemon
visibility commands must return their exact SHA-256 values and each cleanup
check must return exactly `absent`. The wrapper then records exactly one result
for each ClickHouse viewpoint: `container_health`, `host_route`, and
`workload_route`. It does not raw-retry those probes.

An atomic directory lock is acquired before path/probe preflight and held until
restoration finishes. `owner.json` contains the attempt, PID, acquisition time,
and an unguessable ownership token. Existing valid ownership is busy; missing
or malformed ownership is stale/invalid and fails closed. The wrapper never
breaks a stale lock automatically.

Only after all preflight checks pass may `stop_command` run. Restoration
requires the exact Kind container ID, `running`, restart count `0`, exactly one
kube-apiserver, and the configured number (minimum two) of consecutive bounded
`/livez=ok` results. The lock is released afterward. All commands run without a
shell, and stdout is bounded for exact probes. The wrapper prints and atomically
writes exactly one `WRAPPER_RESULT=<json>` record containing ordered check
results as well as the original controller/restore precedence dimensions.

This is local L5 contract evidence only. It does not authorize an external
rehearsal, and live Colima/Kind/ClickHouse behavior remains externally
unverified.

## Local architecture gate

Run the L6 decision entry point from a clean tracked checkout:

```powershell
python scripts/golden_soak/architecture_gate.py
```

It executes the focused runtime/foundation/wrapper tests, Ruff check/format,
`py_compile`, merged Compose validation, Git diff/clean-tree checks, the
finding-closure register, all eight source-pack hashes, UTF-8/LF/NUL policy,
and exact HEAD capture. Child command output is suppressed; the process emits
exactly one line and exits zero only for PASS:

```text
ARCHITECTURE_READY=PASS blockers=0 head=<exact-40-character-head>
```

A failed or malformed check emits one deterministic `BLOCKED` line with
ordered finding or `G-*` gate IDs and exits nonzero. The gate does not retry a
failed command. Protected untracked evidence is ignored, while any tracked
index/worktree difference blocks PASS.

`ARCHITECTURE_READY=PASS` is local architecture evidence only. It does not
prove current Colima/Kind/ClickHouse state or authorize a rehearsal, `r8`,
traffic, soak, rollback, production action, or push.

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
