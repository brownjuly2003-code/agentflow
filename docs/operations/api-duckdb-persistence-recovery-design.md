# API DuckDB persistence and recovery design

**Updated:** 2026-08-27

**Status:** `CAPABILITY_REHEARSAL_REQUIRED`; this file is not an approved operator runbook

**Audience:** developers and operators evaluating a future separately
authorized recovery action for `API_DUCKDB_WAL_REPLAY_FAILURE`

## Purpose and authority boundary

This is the current preservation, recovery, rollback, and authorization-boundary
owner for API DuckDB files on `/data`. It explains repository ownership,
lifetime, fail-closed invariants, the selected future recovery branch, and
layered acceptance. It does not authorize any runtime action.

Reading this document or preparing inputs is not authorization to access target bytes,
mutate runtime state, recover the deployment, or claim production readiness.

Dated execution narrative, consumed identities, and session-by-session
outcomes live only in the
[archived chronology](../archive/operations/api-duckdb-persistence-recovery-chronology-2026-08-10-to-2026-08-23.md).
Non-target capability preparation uses the
[current non-target scratch rehearsal](api-duckdb-non-target-scratch-rehearsal-runbook.md).

## Current evidence freshness

Last recorded facts from the archived original, not a live re-query:

- The remaining proved API workload failure is a local DuckDB open/WAL-replay
  crash during API lifespan, not a missing external dependency and not a
  service-endpoint root cause.
- The original `emptyDir` file set observed around 2026-08-10 was lost on pod
  replacement: the ReplicaSet replaced that pod on 2026-08-18, destroying the
  volume contents with the pod.
- A second organic occurrence of the same WAL-replay assertion was observed
  on 2026-08-23 on the replacement volume. The replacement files used the same
  env basenames; those names come from `DUCKDB_PATH` / usage-path configuration,
  not from the data's age.
- That 2026-08-23 observation recorded two 12,288-byte main files that were
  byte-identical pristine empty databases: no checkpoint had run, and the
  record history sat in the two WAL files. Those bytes replace the lost
  original set as forensic material only while they still exist.
- Production remains `candidate`.
- Last recorded evidence shows no verified external backup is known.
- External dependency recovery is already PASS/consumed and must not be
  repeated for this failure.
- Last recorded preservation feasibility remains `PRESERVATION_PARTIAL`
  because no reviewed crash-consistent quiesce-and-copy path was established.
  Later non-target scratch evidence did not make either corrected quiesce
  branch eligible.

Unknown without a new separately authorized observation: whether the
replacement files still exist, current pod/UID/volume identity, file inventory,
hashes, and any backup created after the archived snapshot.

## Scope and non-goals

### In scope

- Ownership and lifetime of API `/data`, `DUCKDB_PATH`,
  `AGENTFLOW_USAGE_DB_PATH`, chart persistence, embedded control-plane state,
  and ClickHouse serving data as defined by tracked chart/code and preserved
  evidence.
- Recoverability, preservation, rollback, and layered acceptance for
  `API_DUCKDB_WAL_REPLAY_FAILURE`.
- Distinction among chart defaults, historical runtime patches, and last
  recorded live values.
- The current decision record and the authorization boundary a later
  separately authorized slice must satisfy.

### Explicit non-goals

- No cleanup, WAL or base-file deletion, path rotation, pod deletion or
  replacement, Deployment edit, Helm upgrade, volume recreation, backup or
  restore execution, offline repair, traffic, soak, clock/I/O work, Flink
  work, production transition, or push.
- No reuse of consumed non-target scratch identities.
- No redesign of external-dependency recovery, ClickHouse/Iceberg lifecycle,
  Kafka durability, clock stability, idle I/O, soak, or production gates.
- This document does not authorize remediation and is not executable.

## Repository ownership and lifetime

### Volume and path identity

| Asset | Owner / store | Lifetime | Recoverability from repository tooling | Notes |
| --- | --- | --- | --- | --- |
| Kubernetes `/data` | Chart: PVC if `persistence.enabled`, else `emptyDir` | PVC outlives the pod; `emptyDir` survives container restart in the same pod and is destroyed on pod deletion | Chart documents PVC; no automatic backup of either volume type | Last recorded live class was `emptyDir`, default medium, `sizeLimit: 256Mi`. Pod deletion of that volume is irreversible discard |
| `DUCKDB_PATH` base + `.wal` | API process via `DuckDBPool` / `connect_duckdb`; on embedded control plane also hosts webhook/alert/outbox/dead-letter tables through `query_engine._conn` | Lives on `/data` (or `:memory:` if configured) | `scripts/backup.py` can checkpoint and archive local DuckDB+WAL when pointed at openable files, but must not be first-line preservation against a failing open | Last recorded failure was `/data/agentflow_fresh_20260807.duckdb.wal`. Base+WAL are one preservation set |
| `AGENTFLOW_USAGE_DB_PATH` base + `.wal` | `AuthManager` private DuckDB file on embedded profile; PostgreSQL adapter when `controlPlane.store=postgres` | Same volume lifetime as `/data` for a file-backed path | Included as usage role by backup tooling when present and openable; same first-line restriction | Last recorded live path was `/data/agentflow_api_fresh_20260807.duckdb`. An earlier usage-WAL crash is not the remaining primary failure |
| Chart persistence selection | `helm/agentflow` `persistence.enabled` plus `templates/deployment.yaml` / `pvc.yaml` | PVC claim named by release fullname when enabled; otherwise `emptyDir: {}` | Durable topology is a separate program; it does not recover lost `emptyDir` bytes | Tracked default is PVC-on; last recorded stand used `emptyDir` |
| Embedded control-plane state | Default `controlPlane.store=embedded`: tables on the serving DuckDB connection (`DUCKDB_PATH`); usage/sessions on the separate usage file | Per-pod / per-file | Local DuckDB backup only if files are reachable and openable | Last recorded `AGENTFLOW_CONTROLPLANE_STORE` was absent; `embedded` remains an application-default inference, not an explicit live env value |
| ClickHouse serving data | External Compose/ClickHouse volume, outside API `/data` | Independent of the API pod volume | **Not** covered by `scripts/backup.py` or the DuckDB disaster-recovery runbook | Last recorded `SERVING_BACKEND=clickhouse`. Serving data was not the API WAL failure mode |
| PostgreSQL control-plane state | Only when `controlPlane.store=postgres` plus DSN secret | External to the API pod | No PITR/base-backup path is implemented in this repository | Not proved active for the recorded stand |
| YAML/config included by backup | Non-secret `config/` members via `scripts/backup.py` | Host/project files or ConfigMap/Secret mounts | Archived with a SHA-256 manifest | Secrets (`api_keys`, `webhooks`, `tenants`) are excluded by policy |
| YAML/config excluded / K8s-mounted | Helm mounts under `/etc/agentflow/...` | Cluster objects, not DuckDB files | Not recovered from a DuckDB backup archive | Re-apply from source of truth / secret manager |

### Conditional placement

Do not invent live placement from chart defaults alone.

| Logical class | Lives in `DUCKDB_PATH` when | Lives in the usage path when | Lives in PostgreSQL when | Lives in ClickHouse when |
| --- | --- | --- | --- | --- |
| Serving entity tables / pipeline journal | `serving.backend=duckdb` (chart default) | never | never | `serving.backend=clickhouse` (last recorded live value) |
| Webhook queue/log, alert history, outbox, dead-letter | embedded store on `query_engine._conn` | never | `controlPlane.store=postgres` | never (rejected for this state in ADR 0010) |
| `api_usage` / `api_sessions` | never on the shared serving connection | embedded AuthManager file | postgres store | never |
| Webhook registrations / alert rules files | N/A (YAML / ConfigMap, not DuckDB) | N/A | postgres rows when externalized | N/A |

### Chart defaults versus last recorded values

| Layer | What is known | What must not be assumed |
| --- | --- | --- |
| Tracked chart defaults | PVC-on by default; `/data/agentflow.duckdb` and `/data/agentflow_api.duckdb`; embedded control plane; DuckDB serving | That the recorded stand was installed with unmodified defaults |
| Historical task baseline | ClickHouse serving; process role `all`; no explicit control-plane store env; `/data` as `emptyDir` `256Mi`; later patch renamed both DuckDB paths to `*_fresh_20260807.duckdb` without changing the volume class | That those identities remain live after later pod replacement |
| Last recorded metadata | Fresh DuckDB env paths, ClickHouse serving, process role `all`, 256Mi `emptyDir` | That the original 2026-08-10 pod, UID, or file set still exists |
| Last recorded replacement volume | Same env basenames, same WAL-replay assertion, original `emptyDir` set already gone | Current inventory, hashes, or a verified backup |

### Application open path

1. FastAPI lifespan constructs `DuckDBPool(db_path=os.getenv("DUCKDB_PATH", ":memory:"))`.
2. `DuckDBPool.initialize()` creates parent directories for non-memory paths,
   then calls `connect_duckdb(self._db_path)`.
3. Without an encryption key, `connect_duckdb` calls `duckdb.connect(path)`.
   A file open triggers WAL replay for an on-disk database.
4. Failure aborts lifespan and the process exits; Kubernetes marks the
   container failed. Later lifespan steps, including usage-DB initialization
   on the separate path, never run while this open fails.

Treat the remaining primary failure as the later `DUCKDB_PATH` fresh file set,
not the earlier usage-path WAL.

## Preservation and recovery invariants

These are mandatory for any later authorized remediation. None are executed
by this document.

1. **Quiesce / single-writer prerequisite.** No concurrent writer to the same
   DuckDB files. The chart already rejects multi-writer persistent DuckDB;
   still require replica/process exclusivity before any copy or offline open.
   A CrashLooping container that keeps restarting continues to attempt the
   same open; that is not a quiesced writer. Do not copy while restart
   attempts continue. Pod `exec` alone does not make a capture
   crash-consistent.
2. **Preserve the complete set before mutation.** Treat `basename.duckdb` +
   `basename.duckdb.wal` plus any sidecar/temp files found in inventory as one
   preservation set for every logical database under `/data`.
3. **Hash and inventory outside the pod/`emptyDir`.** Record names, sizes,
   mtimes, and SHA-256 (or equivalent) on host-persistent storage outside the
   ephemeral volume before any change.
4. **Sealed master, then disposable working clones.** The first external byte
   copy is a **sealed master**. Never operate on the sealed master or the sole
   live original. Every DuckDB open, WAL replay, checkpoint, or recovery
   experiment must use a new **disposable working clone** derived from that
   master, because an open/replay attempt may change files.
5. **No pod deletion or path rotation before preservation and an explicit
   data disposition decision.** With `/data` as `emptyDir`, **pod deletion**
   or replacement that recreates the volume destroys the current base DB and
   WAL. There is no Kubernetes object that reconstitutes those bytes. That
   discard is **irreversible** and is not rollback-safe repair. Historical
   recovery that deleted a pod to obtain a fresh empty volume was explicit
   data loss, acceptable only after the data owner accepted loss of that
   `emptyDir` content. PVC mode changes lifetime but still does not create
   backups; PVC alone is not a rollback plan.
6. **No standalone WAL deletion.** Deleting only `*.wal` is forbidden. Any
   reset that abandons base+WAL is explicit data loss, not recovery.
7. **No production or readiness claim from a clean empty database alone.** A
   process that starts on a fresh empty file proves only process health, not
   data continuity or production readiness.
8. **Do not repeat external dependency recovery** for this failure.
9. **Repository backup tooling is not a substitute** for preservation of the
   live `emptyDir` unless a verified archive of *these* runtime files is first
   shown to exist.
10. **`scripts/backup.py` is not first-line preservation of a failing live
    set.** `_checkpoint_duckdb` first executes `duckdb.connect(str(db_path))`,
    then `CHECKPOINT`. Opening the current primary path is exactly where
    startup fails during WAL replay. Therefore:
    - do not run `backup.py` directly against the sole failing live set as the
      first preservation step;
    - it may fail before copying because opening the DB triggers the same
      replay;
    - raw byte preservation of the complete quiesced base/WAL/sidecar set must
      precede any DuckDB open/checkpoint attempt;
    - a pre-existing verified archive remains a valid conditional restore
      source if and only if such an archive is identified.

Rollback material, when a later slice is authorized, is an externally
preserved sealed master of the complete database+WAL set plus saved
Deployment/env identity. Working clones used for open/replay experiments are
not the rollback master. Without that external sealed set, any destructive
action has no rollback for embedded DuckDB state on that volume.

## Current recovery decision

Status remains `CAPABILITY_REHEARSAL_REQUIRED`. Neither corrected quiesce
branch (`PAUSED_TASK` nor `KUBELET_GAP`) was proved eligible. The kubelet-stop
emergency candidate was not selected; no quiesce/capture operator runbook is approved.

Recorded decision, not an execution grant:

- Option A (forensic preservation and offline recovery from an external copy)
  remains the fail-closed preservation posture: inventory/copy/hash only after
  reviewed quiesce; sealed master plus disposable working clones only.
- Option B (restore from a verified backup) is unavailable:
  no verified external backup is known; treat one as nonexistent until identified.
- Option C (explicit empty-store reset / discard) is not a first action.
  Synthetic embedded state on this candidate stand may be discarded only
  after one **best-effort read-only capture attempt** has been made and its
  outcome recorded, whether that attempt succeeds or fails.
- Option D (future PVC/durable topology and backup wiring) is a separate
  implementation program. It does not repair current or lost WAL bytes.

Preferred future recovery branch, only inside a separately authorized
rollback-capable slice:

1. Rehearse against a disposable working clone, never against the sealed
   master or the sole live original.
2. Open with `READ_ONLY` so WAL replay is skipped.
3. Capture via `EXPORT DATABASE`.
4. Create fresh store files with new `DUCKDB_PATH` / usage-path basenames.
5. Leave the failing file set in place untouched as forensic material.

This preferred branch is capture-oriented and read-only at the DuckDB layer.
It is not hereby authorized. A DuckDB version bump is not a claimed
remediation while the matching upstream WAL-replay issues remain open. The
pinned runtime is `duckdb == 1.5.4` at both the failing image and later
repository lock; the failure is not version-skew replay. Local non-target
reproduction did not recreate the internal error from a fully flushed or
cleanly torn WAL; an abrupt host restart remains an inference, not root-cause
proof for these bytes.

Consumed non-target scratch identities must not be reused. Their immutable
records are:

- [E22](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e22-2026-08-11.md)
- [E24](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e24-2026-08-11.md)
- [E26](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e26-2026-08-11.md)

Those results, and later non-target metadata/xattr gates, characterize scratch
primitives only. They do not prove target Pod or volume behavior, branch
eligibility, capture safety, or production readiness.

## Layered acceptance criteria

Each layer must pass with recorded evidence. A later layer cannot waive an
earlier failure. This table is an acceptance contract, not a procedure to run.

| Layer | Pass condition | Required recorded evidence | False-green traps |
| --- | --- | --- | --- |
| 1. Preservation | Complete inventory plus external sealed master copies and hashes for every candidate DB set; writers quiesced before byte copy; no mutation of live originals or of the sealed master | Inventory listing; sealed-master paths; SHA-256; quiesce mechanism reference; pod/deploy identity; authorization reference | Claiming “preserved” from logs only; hashing inside-only without an external copy; copying while CrashLoop restarts continue; treating pod `exec` alone as crash-consistent; running `backup.py` against the sole failing live set |
| 2. Offline database/data | A disposable working clone opens, or is classified unrecoverable with proof; table/class inventory for intended data classes; sealed master untouched | Offline open log on a clone; table list or explicit unrecoverable classification; no live apply yet; master hash re-check | Treating “file exists” as “data OK”; opening the sole original or the sealed master; reusing a previously opened clone as if it were still pristine |
| 3. API startup/readiness | API process starts and readiness passes against the intended restored or repaired data set | Pod Ready; health/ready evidence; absence of WAL replay error in startup logs | Ready on a different empty path after silent rotation |
| 4. Data continuity | Expected logical classes still present or explicitly accepted lost | Query/count/sample checks appropriate to class; ClickHouse serving checked only if in scope | Continuity claim from empty schema create-on-boot; demo seed mistaken for recovery |
| 5. Restart / pod-lifetime | Restart *within the same pod* retains data when the volume is `emptyDir`; pod replacement tested only after durability design or accepted loss | Controlled restart evidence; volume source re-confirmed | Passing a container restart while still `emptyDir` and calling it durable |
| 6. Production claim boundary | Production remains `candidate` until separate production gates pass | Explicit non-claim; dependency/workload/clock/I/O/soak/traffic gates not silently marked pass | Elevating production because the API became Ready |

### Explicit non-claims

After any future successful API Ready, and after any capture or export:

- Not a production acceptance. Production remains `candidate`.
- Not a soak pass and not a traffic pass.
- Not proof of durability: `emptyDir` still dies with the pod.
- Not proof of WAL root-cause physics without forensic analysis on disposable
  working clones.
- Not proof that DuckDB can replay the live WAL, that any logical table is
  recoverable, or that `EXPORT DATABASE` succeeded, until that work is
  recorded on a clone under a separate authorization.
- Not proof that external dependency recovery was incomplete (it is consumed).
- Not a C05, quiesce-branch, capture, restore, or runbook approval.

## Blockers and authorization boundary

Any target-byte access, filesystem/database-byte copy, DuckDB open on live or
captured files, quiesce, capture, cleanup, restore, pod mutation, traffic, or
production transition requires a new explicit authorization. Reading this
file, updating documentation, or preparing a scratch identity does not supply
that authorization.

Stop, or remain blocked, when any of the following is true:

- Separate written authorization is absent for the proposed runtime
  interaction.
- The proposed action would access target bytes or mutate runtime state.
- Pod/UID/volume identity has drifted and the owner has not accepted the new
  identity.
- No reviewed quiesce-and-copy mechanism exists for a crash-consistent capture
  of the complete base/WAL/sidecar set to host-persistent storage outside the
  pod.
- Proposed capture would copy while CrashLoop restarts continue, or would
  write into the same `emptyDir` or another ephemeral location.
- Proposed first preservation step is `scripts/backup.py` or any other DuckDB
  open/checkpoint against the sole failing live set.
- Proposed action is pod deletion, path rotation, WAL-only delete, helper or
  ephemeral-container injection, kubelet stop, or restore into the live
  volume.
- The destination for an external sealed master is absent or unrehearsed.
- The only remaining files are already lost and no sealed master or verified
  backup exists; discard then has no rollback.

A future authorized slice must still keep rollback material before mutation,
use a disposable working clone for every open/replay/export experiment, and
stop before production, soak, traffic, or durability claims.

## Related documents

- [Operations index](README.md)
- [Archived operations](../archive/operations/README.md)
- [Archived recovery chronology](../archive/operations/api-duckdb-persistence-recovery-chronology-2026-08-10-to-2026-08-23.md)
- [Current non-target scratch rehearsal](api-duckdb-non-target-scratch-rehearsal-runbook.md)
- [Disaster recovery runbook](disaster-recovery.md) for local openable DuckDB
  backup/restore only, not first-line preservation of this failing set
- [Engineering status](../STATUS.md) for current production-candidate gates
