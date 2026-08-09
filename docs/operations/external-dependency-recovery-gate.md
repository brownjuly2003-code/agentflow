# External dependency recovery gate

**Status:** implemented and locally tested on 2026-08-09; live recovery has
not been executed.

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
5. From the kind control-plane, require successful ClickHouse `/ping`, MinIO
   `/minio/health/live`, and Iceberg REST `/v1/config` probes.

Only after all five stages does the JSON result set
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
and the absence of create/recreate/delete Compose commands.
