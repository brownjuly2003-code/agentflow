# External dependency recovery gate

**Status:** one live recovery failed safe and rolled back on 2026-08-09; the
bounded Iceberg REST readiness correction is implemented and locally tested,
but has not been exercised live.

This runbook covers the current
`COLIMA_RESTART_DEPENDENCY_LIFECYCLE_GAP`: restoring the existing ClickHouse,
MinIO, and Iceberg REST containers after the Colima VM restarted while their
Docker restart policy was `no`. It does not remediate the independent API
DuckDB WAL failure, verify workloads, change Kubernetes objects, or establish
clock, idle-I/O, traffic, soak, or production readiness.

## Safety contract

[`scripts/recover_external_dependencies.py`](../../scripts/recover_external_dependencies.py)
is fail-closed around the owners recorded by the 2026-08-09 lifecycle RCA.
Before any mutation it requires:

- the exact ClickHouse and Iceberg Compose service sets;
- the expected project, service, Compose-file, image, and restart-policy
  labels on every existing container;
- the existing `agentflow-ch-rv-20260802-01-data` named volume mounted at
  `/var/lib/clickhouse`;
- the existing MinIO container, whose writable layer contains its data;
- a previously successful, exited `minio-init` one-shot container; and
- the running `agentflow-reverify-ed03fc47-control-plane` kind node.

The gate uses `docker compose start SERVICE`. It never runs `up`, `down`,
`rm`, or a volume-delete command, so it cannot silently create a replacement
MinIO container or recreate ClickHouse without its recorded volume.

## Read-only preflight

From the repository root, run:

```powershell
python scripts/recover_external_dependencies.py
```

The default mode connects to the exact remote Colima Docker socket but only
runs Compose configuration and Docker inspection commands. A successful
result has `status: preflight_passed` and keeps
`ready_for_workload_verification: false`. Any missing owner, changed label,
unexpected service, unsafe state, or persistence mismatch exits nonzero
before a start/stop operation.

### Latest recorded preflight

The default preflight ran once from commit `5b5e746` on 2026-08-09 from
`23:38:16.610Z` through `23:38:22.032Z`. It exited `0` with
`status: preflight_passed`, `execute: false`, and
`ready_for_workload_verification: false`.

The recorded containers remained stopped: ClickHouse and Iceberg REST exited
`137`; MinIO and `minio-init` exited `0`. The `unhealthy` values retained on
the exited ClickHouse and MinIO containers are their last Docker health
state, not live endpoint checks. No container start/stop, Docker exec,
Colima/Kubernetes mutation, workload verification, or secret read occurred.

Exact local evidence:
`.codex-grok-tasks/external-dependency-recovery-preflight-20260809-codex01/`.
Preflight success proves that the recorded owners and persistence
prerequisites are intact; it does not establish dependency readiness.

## Separately authorized live recovery

Only a later live-recovery slice may run:

```powershell
python scripts/recover_external_dependencies.py `
  --execute `
  --acknowledge-live-recovery COLIMA_RESTART_DEPENDENCY_LIFECYCLE_GAP
```

The acknowledgement is intentionally exact. The execution order is:

1. Start the existing ClickHouse container and require Docker health.
2. Start the existing MinIO container and require Docker health.
3. Restart `minio-init`, treat it as a one-shot, and require `exited (0)`.
4. Start Iceberg REST and require its container to remain running.
5. From the kind control-plane, require successful ClickHouse `/ping` and
   MinIO `/minio/health/live` probes.
6. Retry only Iceberg REST `/v1/config` connection-refusal (`curl (7)`)
   failures every two seconds within the configured timeout. Inspect fresh
   container state after each refusal; fail immediately on a terminal state
   or any non-connection-refusal error.

Only after all six stages does the JSON result set
`ready_for_workload_verification: true`. That result authorizes a separate
workload-verification decision; it is not itself a workload recovery claim.

## Failure and rollback

On any post-start failure, the gate stops services in reverse order only when
this invocation started them. It leaves pre-existing healthy services
running. A still-running `minio-init` is stopped, while a successfully
completed one-shot is already terminal and is not restarted during rollback.

Rollback uses scoped `docker compose stop`; it does not remove containers,
the ClickHouse named volume, or the MinIO writable layer. The gate reports
both the original failure and any scoped-stop failure, and never emits a
ready result on either path.

## Local verification

The recovery state machine and command-safety contract are covered without a
Docker or SSH connection:

```powershell
python -m pytest tests/unit/test_external_dependency_recovery.py -q
python -m ruff check scripts/recover_external_dependencies.py `
  tests/unit/test_external_dependency_recovery.py
```

The tests pin one-shot ordering, preflight-before-mutation, named-volume
failure, reverse rollback, preservation of a pre-existing healthy service,
bounded Iceberg connection-refusal retry, terminal-state stop, non-transient
error propagation, and the absence of create/recreate/delete Compose commands.

## Latest recorded live recovery

One separately authorized recovery ran from entry HEAD `8209cf6` on
2026-08-09. Grok executed the exact acknowledged command once through
`local_grok_cli` (`grok-4.5-build`; run
`deproject-dep-live-20260809-grok01`). The command exited `1`; stdout was
empty and stderr reported `curl (7)` connection failure to
`172.18.0.1:8181` during the Iceberg REST `/v1/config` kind-network probe.
No ready JSON was emitted and `ready_for_workload_verification` remains
false.

The recovery command was not retried. Its failure path reported no rollback
error. Grok's one post-rollback read-only preflight and one independent Codex
preflight both returned `preflight_passed` with every dependency stopped:
ClickHouse and MinIO exited `0`, `minio-init` exited `0`, and Iceberg REST
exited `143`. The retained `unhealthy` values for stopped ClickHouse and
MinIO are historical Docker health state, not live readiness.

The failure proved that the single Iceberg REST probe ran before the endpoint
accepted a connection. It did not prove that the endpoint could never become
ready: the state machine at entry HEAD waited only for container `running`
and then performed one immediate `/v1/config` probe. Classification:
`ICEBERG_REST_READINESS_GATE_INCOMPLETE`. The current local implementation
retries only that observed transient error under a bounded condition wait; no
live retry has occurred.

Exact local evidence is untracked under
`.codex-grok-tasks/external-dependency-live-recovery-20260809-grok01/`:

- `result.json` — SHA-256
  `641a1a7a7ff22f9666ef514233f7b37b16fec86ff4cbaed5d1f5916c40ece0a9`;
- `post-rollback-preflight.json` — SHA-256
  `38c7b8f93c275556266ff2f0e0ca94cc9fba05a11c84845aa0d969726f56c763`;
- `recovery-stderr.txt` — SHA-256
  `cc952c2ee7191ec3c4b755c64c4a09e53b3ec038f4f6af48b4ddfa82c0f99da1`.

No workload verification, API WAL work, Kubernetes or Colima mutation,
traffic, production transition, commit by Grok, or push occurred.

## Next-session transparent resume

Use this section as the compact-safe operator snapshot. Refresh
`git status --short --branch --untracked-files=no` and `git log -2 --oneline`
first; repository state is authoritative if it differs from the snapshot.

### Recorded identities

| Field | Recorded value |
| --- | --- |
| Evidence commit | `f5c7f6c2e7db7113719941362ba79e1b661f79c2` |
| Branch at capture | `main`, ahead of `origin/main` by 46 |
| Executor | Codex; no Grok or delegated agent |
| SSH host | `deproject-mac` |
| Colima profile | `agentflow-fc5-7113966` |
| Docker socket | `/Users/julia/.colima/agentflow-fc5-7113966/docker.sock` |
| Kind node | `agentflow-reverify-ed03fc47-control-plane` |
| ClickHouse project/container | `agentflow-ch-rv-20260802-01` |
| ClickHouse Compose file | `/tmp/agentflow-chk-restore-rv-20260802-01/clickhouse-compose.yml` |
| ClickHouse volume | `agentflow-ch-rv-20260802-01-data` |
| Iceberg project | `agentflow-iceberg-rv-20260802-01` |
| Iceberg Compose file | `/tmp/agentflow-iceberg-ed03fc47-20260801-01/docker-compose.iceberg.yml` |

The exact preflight invocation was
`.venv/Scripts/python.exe scripts/recover_external_dependencies.py`, with no
additional arguments. It issued eight separate bounded remote Docker calls:
two `compose config --services` calls, one named-volume inspection, four
dependency-container inspections, and one kind-node inspection. It issued no
Docker exec or mutating command.

The CLI records normalized gate output, not a raw transcript of each SSH
command. That missing per-command transcript is an explicit evidence limit;
the fixed command construction remains reviewable in
`scripts/recover_external_dependencies.py`. Exact local evidence is untracked
by Git and therefore available only in this workspace:

- `preflight-output.json` — SHA-256
  `d83472b5320fe4740d8972a616566cc9da6df0b82ace2a8651aefb892b1c4573`;
- `result.json` — SHA-256
  `4121ca63aa8ddfd1bd0ebf87f4c232d406f0d004dc9be24b049f6028a4db4db1`.

Both files are under
`.codex-grok-tasks/external-dependency-recovery-preflight-20260809-codex01/`.
If they are absent or their hashes differ, trust the committed summary only
and report the local-evidence gap; do not recreate evidence by silently
rerunning the preflight.

### Current claim boundary

- The first live recovery identity is consumed. Do not repeat it without a
  tested readiness-gate change or new diagnostic evidence.
- The bounded readiness-gate change is locally green. Dependency state is
  unchanged because no second live recovery ran.
- Dependency readiness is false because all dependency containers remain
  exited. Workload recovery is also false.
- Restoring ClickHouse and Iceberg/MinIO cannot repair the independent API
  DuckDB WAL replay failure. API remediation remains a separate slice.
- Option A remains failed and rolled back. Clock stability and idle-I/O remain
  failed/open. Traffic, Flink, watcher, hold, and production transition remain
  unperformed and out of scope; production is `candidate`, and push remains
  unauthorized.
- MinIO data lives in the existing container writable layer rather than a
  named volume. A missing/replaced MinIO container is therefore a hard
  preflight failure, not permission to create a replacement.

### Next decision

The next direct dependency action is one separately authorized runtime slice
for a new live recovery attempt. It must use a new evidence identity, preserve
the exact command output, and stop after success or after one failure/rollback
record. Workload verification remains a later separate slice.
