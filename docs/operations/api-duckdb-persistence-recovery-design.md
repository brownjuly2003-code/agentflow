# API DuckDB persistence and WAL recovery design

**Date:** 2026-08-10

**Status:** Design only — not executed

**Repository HEAD at authoring:** `319c8d67ce39a33a928d6c1e93566d468034f9e1`

**Failure under design:** `API_DUCKDB_WAL_REPLAY_FAILURE` on
`/data/agentflow_fresh_20260807.duckdb.wal`

## Outcome

The remaining proved API workload failure is a **local DuckDB open/WAL-replay
crash during API lifespan**, not a missing external dependency and not a
service-endpoint root cause. Repository ownership shows `/data` is either a
PVC or an `emptyDir` selected by chart `persistence.enabled`; prior runtime
evidence for this stand verified **`emptyDir`**, which survives container
restarts inside the same pod and is **destroyed with the pod**. No verified
backup of the current runtime files is known. The selected design is therefore
**fail-closed forensic preservation and offline recovery from an external
copy**, stopping before any cleanup, path rotation, pod deletion, restore into
the live volume, or production claim. External dependency recovery is already
PASS/consumed and must not be repeated for this failure.

## Scope and non-goals

### In scope

- Ownership and lifetime of API `/data`, `DUCKDB_PATH`, and
  `AGENTFLOW_USAGE_DB_PATH` as defined by tracked chart/code and preserved
  runtime evidence.
- Recoverability, backup/preservation, rollback, and layered acceptance for
  `API_DUCKDB_WAL_REPLAY_FAILURE`.
- Distinction among chart defaults, historical runtime patches, and live
  values that remain unqueried.
- Exact next separately authorized gate (metadata / preservation-feasibility
  only).

### Explicit non-goals / boundary

- No cleanup, WAL or base-file deletion, path rotation, pod deletion/replacement,
  Deployment edit, Helm upgrade, volume recreation, backup/restore execution,
  offline repair attempt, traffic, soak, clock/I/O work, Flink work, production
  transition, or push.
- No SSH, Docker, Kubernetes, live pod `exec`/copy, or any runtime mutation in
  this slice.
- No redesign of external-dependency recovery, ClickHouse/Iceberg lifecycle,
  Kafka durability, clock stability, idle I/O, soak, or production gates.
- This document does not authorize remediation. It defines the contract a later
  authorized slice must satisfy.

## Evidence ledger

Claims below use these categories: **Observed**, **Repository contract**,
**Inference**, **Unknown**, **Decision**.

| ID | Source | Freshness / claim limit |
| --- | --- | --- |
| E1 | [AGENT_STATE.md](../../AGENT_STATE.md) top resume block `HANDOFF:CURRENT_RESUME_INDEX_20260810_02` | Docs-only update at HEAD `319c8d67…`; last runtime observation `2026-08-10T00:30:13.1767165Z`; not a live re-query |
| E2 | [docs/SESSION_HANDOFF.md](../SESSION_HANDOFF.md) matching top block | Same freshness boundary as E1 |
| E3 | [`.codex-grok-tasks/workload-recovery-verification-20260810-codex01/result.json`](../../.codex-grok-tasks/workload-recovery-verification-20260810-codex01/result.json) | Observed once at `2026-08-10T00:30:13.1767165Z`; eight read-only kubectl queries; no `exec` |
| E4 | [same pack `result.md`](../../.codex-grok-tasks/workload-recovery-verification-20260810-codex01/result.md) | Summary of E3; no remediation |
| E5 | [same pack `evidence.md`](../../.codex-grok-tasks/workload-recovery-verification-20260810-codex01/evidence.md) | Decisive API previous-log and workload identities; no filesystem inspection |
| E6 | [colima-runtime-stabilization.md](../../colima-runtime-stabilization.md) “Workload recovery RCA” and later sections | RCA at `2026-08-09T22:46:11Z`; verification section at `2026-08-10T00:30:13Z`; emptyDir stated as local API path class, WAL origin still unproven without `exec` |
| E7 | [external-dependency-recovery-gate.md](external-dependency-recovery-gate.md) latest workload result / next decision | Dependency recovery PASS/consumed; does not repair API WAL |
| E8 | [`.codex-grok-tasks/golden-4h-soak-api-emptydir-recovery-reinstall-20260802.md`](../../.codex-grok-tasks/golden-4h-soak-api-emptydir-recovery-reinstall-20260802.md) | **Historical** task brief (2026-08-02): prior API pod failed on `/data/agentflow_api.duckdb.wal`; task required `/data` to be verified `emptyDir` before pod delete; **not re-queried on 2026-08-10** |
| E9 | [`.codex-grok-tasks/golden-4h-soak-runtime-20260807-05/_fix_api_and_resume.sh`](../../.codex-grok-tasks/golden-4h-soak-runtime-20260807-05/_fix_api_and_resume.sh) | **Historical runtime patch provenance** (2026-08-07): set both `AGENTFLOW_USAGE_DB_PATH` and `DUCKDB_PATH` to `*_fresh_20260807.duckdb` when no hostPath; not the tracked chart default |
| E10 | [same pack `runtime-result.md`](../../.codex-grok-tasks/golden-4h-soak-runtime-20260807-05/runtime-result.md) | Summary emphasized usage-path fix; does not erase the dual env patch in E9 |
| E11 | [`.codex-grok-tasks/full-e2e-live-execute-20260801.md`](../../.codex-grok-tasks/full-e2e-live-execute-20260801.md) | Earlier deployment profile: ClickHouse serving + `DUCKDB_PATH=/data/agentflow.duckdb` + `AGENTFLOW_USAGE_DB_PATH=/data/agentflow_api.duckdb` on task `emptyDir` |
| E12 | [helm/agentflow/values.yaml](../../helm/agentflow/values.yaml), [templates/deployment.yaml](../../helm/agentflow/templates/deployment.yaml), [templates/pvc.yaml](../../helm/agentflow/templates/pvc.yaml), [templates/_env.tpl](../../helm/agentflow/templates/_env.tpl), [values.schema.json](../../helm/agentflow/values.schema.json) | Tracked chart ownership; defaults ≠ proved live values |
| E13 | [src/serving/api/main.py](../../src/serving/api/main.py), [db_pool.py](../../src/serving/db_pool.py), [duckdb_connection.py](../../src/serving/duckdb_connection.py) | Startup path that opens `DUCKDB_PATH` |
| E14 | [control_plane/store.py](../../src/serving/control_plane/store.py), [embedded.py](../../src/serving/control_plane/embedded.py), [ADR 0009](../decisions/0009-control-plane-state-and-scaling-gate.md), [ADR 0010](../decisions/0010-control-plane-externalization-postgres.md) | Conditional ownership of embedded vs PostgreSQL control-plane state |
| E15 | [docs/disaster-recovery.md](../disaster-recovery.md), [scripts/backup.py](../../scripts/backup.py), [verify_backup.py](../../scripts/verify_backup.py), [restore.py](../../scripts/restore.py) | Local DuckDB/config backup tooling; not proved wired to this emptyDir; not first-line preservation against a failing open (see invariant 10) |
| E16 | [`.codex-grok-tasks/checkpoint-restore-reverify-20260802-01/api-deployment.yaml`](../../.codex-grok-tasks/checkpoint-restore-reverify-20260802-01/api-deployment.yaml) | **Historical task Deployment baseline** (preserved manifest, not a live 2026-08-10 query and **not** a claim that this file was rendered by the tracked Helm chart): Deployment `agentflow-chk-restore-rv-api-20260802-01`; `DUCKDB_PATH=/data/agentflow.duckdb`; `AGENTFLOW_USAGE_DB_PATH=/data/agentflow_api.duckdb`; `AGENTFLOW_PROCESS_ROLE=all`; no explicit `AGENTFLOW_CONTROLPLANE_STORE` (application default therefore `embedded` at that baseline); `/data` is `emptyDir` with `sizeLimit: 256Mi`. Later E9 changes the two DuckDB env paths and scales the Deployment but does not change volume or process-role fields. Unrecorded later mutation is **not** ruled out |

## Current failure data-flow trace

### Observed startup failure (E3–E5, E6)

**Observed.** API pod
`agentflow-chk-restore-rv-api-20260802-01-59489dd45c-kk8tf` (UID
`c9d26829-c57f-4550-a86f-cdcc41e719fd`, image
`agentflow/api:ed03fc47-iceberg-live-20260801-01`) was not Ready, waiting
`CrashLoopBackOff`, last termination reason `Error`, exit code `3`, last
start/finish `2026-08-10T00:29:59Z`–`00:30:04Z`. Previous log showed:

```text
db_pool.initialize() -> connect_duckdb(self._db_path) -> duckdb.connect(path)
_duckdb.InternalException: INTERNAL Error: Failure while replaying WAL file
"/data/agentflow_fresh_20260807.duckdb.wal":
Calling DatabaseManager::GetDefaultDatabase with no default database set
ERROR: Application startup failed. Exiting.
```

**Observed limits.** No pod filesystem inspection was performed. The evidence
proves *where* startup dies and *which path* DuckDB was replaying; it does
**not** prove why the WAL became unreplayable. An abrupt Colima restart is a
**plausible Inference** (E6 host/dependency lifecycle and emptyDir history),
not a proven corruption origin.

**Observed.** Bridge and materializer recovered after external dependency
recovery; Redis and Kafka stayed Ready. The empty API Service endpoint is a
readiness consequence, not a second root cause (E3, E7).

### Chart and env ownership (Repository contract, E12)

1. Chart defaults (`values.yaml`):
   - `persistence.enabled: true`, `mountPath: /data`
   - `config.duckdbPath: /data/agentflow.duckdb`
   - `config.usageDbPath: /data/agentflow_api.duckdb`
   - `serving.backend: duckdb`
   - `controlPlane.store: embedded`
   - `replicaCount: 1`
2. Volume selection (`templates/deployment.yaml`):
   - mount `/data` always;
   - if `persistence.enabled` → PVC claim named by release fullname;
   - else → `emptyDir: {}`.
3. PVC resource (`templates/pvc.yaml`) is rendered only when
   `persistence.enabled`.
4. Env injection (`templates/_env.tpl`):
   - `DUCKDB_PATH` ← `config.duckdbPath`
   - `AGENTFLOW_USAGE_DB_PATH` ← `config.usageDbPath`
   - `AGENTFLOW_CONTROLPLANE_STORE` ← `controlPlane.store`
5. Render guards (`templates/deployment.yaml`):
   - persistent DuckDB rejects multi-writer replica/autoscaling shapes;
   - multi-replica also requires `serving.backend=clickhouse` **and**
     `controlPlane.store=postgres`.

### Task Deployment baseline vs chart defaults (Historical provenance, E16 → E9)

**Historical provenance chain — not a fresh 2026-08-10 live query.** The
preserved task manifest (E16) establishes the task Deployment baseline for
`agentflow-chk-restore-rv-api-20260802-01`. It is **not** claimed to have been
rendered by the tracked Helm chart (E12); it is a preserved task artifact that
records:

- Deployment name `agentflow-chk-restore-rv-api-20260802-01` (matches the
  failing pod owner prefix in E3–E5);
- `DUCKDB_PATH=/data/agentflow.duckdb` and
  `AGENTFLOW_USAGE_DB_PATH=/data/agentflow_api.duckdb` at baseline;
- `AGENTFLOW_PROCESS_ROLE=all`;
- no explicit `AGENTFLOW_CONTROLPLANE_STORE` field, therefore the application
  default is `embedded` at that baseline;
- volume `/data` as `emptyDir` with `sizeLimit: 256Mi`.

The later 2026-08-07 script (E9) changes the two DuckDB env paths to the
`*_fresh_20260807.duckdb` names (matching the currently failing WAL basename)
and scales the Deployment, but does **not** change the volume or process-role
fields in that historical chain.

**Current uncertainty remains explicit:** unrecorded mutation after E9 is not
ruled out. Exact live env values, volume source, and control-plane store kind
must still be confirmed with a separately authorized read-only metadata query
before any runtime preservation or recovery work.

### Application open path (Repository contract, E13)

1. FastAPI lifespan (`main.py`) constructs `DuckDBPool(db_path=os.getenv("DUCKDB_PATH", ":memory:"))`.
2. `DuckDBPool.initialize()` creates parent directories for non-memory paths,
   then calls `connect_duckdb(self._db_path)`.
3. Without encryption key, `connect_duckdb` calls `duckdb.connect(path)`
   (file open triggers WAL replay for an on-disk database).
4. Failure aborts lifespan → process exit → Kubernetes marks the container
   failed (observed exit `3`).
5. Later lifespan steps that never run while this fails include QueryEngine
   construction, control-plane store binding, and AuthManager usage-table
   ensure. The crash is therefore **before** usage-DB initialization on the
   separate path.

### Path identity of the current WAL (Observed + historical provenance)

| Path class | Value | Classification |
| --- | --- | --- |
| Failing WAL | `/data/agentflow_fresh_20260807.duckdb.wal` | **Observed** in 2026-08-09/10 logs |
| Implied base file | `/data/agentflow_fresh_20260807.duckdb` | **Inference** from DuckDB naming; file presence not re-listed |
| Chart default primary | `/data/agentflow.duckdb` | **Repository contract**; not the failing name |
| Task baseline primary (E16) | `DUCKDB_PATH=/data/agentflow.duckdb` | **Historical** task manifest; superseded in name by E9 for this chain |
| Historical patch primary | `DUCKDB_PATH=/data/agentflow_fresh_20260807.duckdb` | **Observed** script provenance (E9) |
| Historical patch usage | `AGENTFLOW_USAGE_DB_PATH=/data/agentflow_api_fresh_20260807.duckdb` | **Observed** script provenance (E9); summary (E10) emphasized this earlier usage fix |
| Prior failed usage WAL | `/data/agentflow_api.duckdb.wal` | **Observed** earlier (E8); **not** the current remaining primary failure |

**Decision for operators:** treat the current primary failure as the **later
`DUCKDB_PATH` fresh file set**, not the earlier `agentflow_api.duckdb.wal`
usage path.

## Ownership matrix

| Asset | Owner / store | Lifetime | Recoverability from repository tooling | Notes for this stand |
| --- | --- | --- | --- | --- |
| Kubernetes `/data` volume | Chart: PVC if `persistence.enabled`, else `emptyDir` | PVC: independent of pod; `emptyDir`: survives container restart in same pod, **destroyed on pod deletion** | Chart documents PVC; no automatic backup of either volume type | **Historical provenance (E16 baseline, E8 proof, E9 did not change volume fields):** task Deployment used `emptyDir` (`sizeLimit: 256Mi` in E16). **Unknown now without a fresh pod-spec query** after possible later unrecorded mutation; do not pretend re-verification on 2026-08-10 |
| `DUCKDB_PATH` base + `.wal` | API process via `DuckDBPool` / `connect_duckdb`; on embedded control plane, also hosts webhook/alert/outbox/dead-letter tables through `query_engine._conn` | Lives on `/data` (or `:memory:` if configured) | `scripts/backup.py` can checkpoint+archive local DuckDB+WAL when pointed at openable files, but **must not** be first-line preservation against the sole failing live set (invariant 10) | **Observed** failure on `agentflow_fresh_20260807.duckdb.wal`. Base+WAL are one preservation set. Path names: E16 baseline → E9 fresh rename |
| `AGENTFLOW_USAGE_DB_PATH` base + `.wal` | `AuthManager` private DuckDB file on embedded profile; PostgreSQL adapter when `controlPlane.store=postgres` | Same volume lifetime rules as `/data` for file-backed path | Included as usage role by backup tooling when present and openable; same first-line restriction as primary | Earlier CrashLoop used `agentflow_api.duckdb.wal` (E8); historical patch moved usage to `agentflow_api_fresh_20260807.duckdb` (E9). Current remaining failure is **not** that usage WAL |
| ClickHouse serving data | External Compose/ClickHouse volume `agentflow-ch-rv-20260802-01-data` (dependency gate identities) | Outside API pod `/data` | **Not** covered by `scripts/backup.py` / disaster-recovery DuckDB runbook | Bridge recovered with backend `clickhouse` after dependency recovery (E3, E7). Independent of API WAL |
| Embedded control-plane state | Default `controlPlane.store=embedded`: tables on serving DuckDB connection (`DUCKDB_PATH`); usage/sessions on separate usage file | Per-pod / per-file | Local DuckDB backup only if files are reachable and openable | **Conditional.** Live `AGENTFLOW_CONTROLPLANE_STORE` value was not re-dumped in E3–E5. E16 baseline has no explicit store env → application default `embedded`; chart default and ADR single-replica profile are also embedded |
| PostgreSQL control-plane state | Only when `controlPlane.store=postgres` + DSN secret | External to API pod | No PITR/base-backup path implemented in this repo (disaster-recovery.md) | Not proved active for this deployment from supplied evidence |
| YAML/config included by backup | Non-secret `config/` members via `scripts/backup.py` | Host/project files or ConfigMap/Secret mounts | Archived with SHA-256 manifest | Secrets (`api_keys`, `webhooks`, `tenants`) **excluded** by policy |
| YAML/config excluded / K8s-mounted | Helm mounts config ConfigMap and secret material under `/etc/agentflow/...` | Cluster objects, not DuckDB files | Not recovered from DuckDB backup archive | Re-apply from source of truth / secret manager, not from DuckDB WAL repair |

### Conditional ownership (do not invent live placement)

| Logical class | Lives in `DUCKDB_PATH` when… | Lives in usage path when… | Lives in PostgreSQL when… | Lives in ClickHouse when… | Missing runtime evidence for this pod |
| --- | --- | --- | --- | --- | --- |
| Serving entity tables / pipeline journal | `serving.backend=duckdb` (chart default) | never | never | `serving.backend=clickhouse` (historical e2e/soak profile E11; E16 task baseline also uses ClickHouse serving) | Live `SERVING_BACKEND` not re-queried in E3–E5 |
| Webhook queue/log, alert history, outbox, dead-letter | embedded store on `query_engine._conn` → `DUCKDB_PATH` | never | `controlPlane.store=postgres` | never (CH rejected for this state in ADR 0010) | Live control-plane store kind not re-queried; E16 baseline implies embedded default |
| `api_usage` / `api_sessions` | never on shared conn (ADR 0010 inventory) | embedded AuthManager file | postgres store | never | Live usage path may still be the 2026-08-07 fresh name (E9), unconfirmed now |
| Webhook registrations / alert rules files | N/A (YAML paths / ConfigMap mounts, not DuckDB) | N/A | postgres rows when externalized | N/A | Exact live registration paths not re-queried |

## Chart defaults vs historical patches vs live unknown

| Layer | What is known | What must not be assumed |
| --- | --- | --- |
| Tracked chart defaults | PVC-on by default; paths `/data/agentflow.duckdb` and `/data/agentflow_api.duckdb`; embedded control plane; DuckDB serving backend | That the stand was installed with unmodified defaults |
| Task Deployment baseline (E16, 2026-08-02) | Preserved manifest for Deployment `agentflow-chk-restore-rv-api-20260802-01`: ClickHouse serving env; both DuckDB paths at chart-like names; `AGENTFLOW_PROCESS_ROLE=all`; no explicit control-plane store env → application default `embedded`; `/data` = `emptyDir` `sizeLimit: 256Mi`. **Not** claimed to be Helm-rendered from E12 | That those exact fields remain live after later patches or unrecorded mutation |
| Historical e2e profile (2026-08-01, E11) | ClickHouse serving; both DuckDB paths on task `emptyDir`; process role `api` | That those exact filenames still apply after later patches |
| Historical emptyDir proof (2026-08-02, E8) | Prior API pod `/data` verified `emptyDir`; recovery by **pod delete** intentionally discarded volume contents | That pod delete is still safe or authorized; that emptyDir still holds without a fresh query |
| Historical fix script (2026-08-07, E9–E10) | No hostPath → `set env` both usage and primary to `*_fresh_20260807.duckdb`; scales Deployment; does **not** change volume or process-role fields relative to the E16 baseline chain; summary text focused on usage | That only usage was changed; current failure is on the primary fresh WAL; that no later unrecorded mutation occurred |
| Latest read-only verification (2026-08-10, E3–E5) | Crash on `/data/agentflow_fresh_20260807.duckdb.wal`; same pod UID as pre-dependency-recovery | Live env dump, volume source, file inventory, hashes, or existence of a backup |

**Unknown without a fresh authorized runtime query:** exact Deployment env
values, volume source on the current pod template, file listing under `/data`,
file sizes/mtimes/hashes, whether base DB exists beside the WAL, and whether
any external backup of those files exists.

## Recovery invariants

These are mandatory for any later authorized remediation. None are executed
here.

1. **Quiesce / single-writer prerequisite.** No concurrent writer to the same
   DuckDB files. Chart already rejects multi-writer persistent DuckDB; still
   require replica/process exclusivity before any copy or offline open.
   A CrashLooping container that keeps restarting continues to attempt the
   same open; that is **not** a quiesced writer. Do not copy while restart
   attempts continue. Pod `exec` alone does not make a capture
   crash-consistent.
2. **Preserve the complete set before mutation.** Treat
   `basename.duckdb` + `basename.duckdb.wal` (+ any sidecar/temp files found
   in inventory) as one preservation set for every logical database under
   `/data`.
3. **Hash and inventory outside the pod/emptyDir.** Record names, sizes,
   mtimes, and SHA-256 (or equivalent) on host-persistent storage outside the
   ephemeral volume before any change.
4. **Sealed master, then disposable working clones.** The first external byte
   copy is a **sealed, hash-verified master**. Never operate on the sealed
   master or the sole live original. Every DuckDB open, WAL replay,
   checkpoint, or recovery experiment must use a **new disposable working
   clone** derived from that master, because an open/replay attempt may
   change files.
5. **No pod deletion or path rotation before preservation and an explicit
   data disposition decision.** Pod deletion of an `emptyDir` volume is
   irreversible data discard, not rollback-safe repair.
6. **No standalone WAL deletion.** Deleting only `*.wal` is forbidden. Any
   reset that abandons base+WAL is **explicit data loss**, not recovery.
7. **No production/readiness claim from a clean empty database alone.** A
   process that starts on a fresh empty file proves only process health, not
   data continuity or production readiness.
8. **Do not repeat external dependency recovery** for this failure (E7).
9. **Repository backup tooling is not a substitute for preservation of the
   live emptyDir** unless a verified archive of *these* runtime files is
   first shown to exist.
10. **`scripts/backup.py` is not first-line preservation of a failing live
    set (Repository contract, E15).** `_checkpoint_duckdb` first executes
    `duckdb.connect(str(db_path))`, then `CHECKPOINT`. Opening the current
    primary path is exactly where startup fails during WAL replay. Therefore:
    - do **not** run `backup.py` directly against the sole failing live set as
      the first preservation step;
    - it may fail **before** copying because opening the DB triggers the same
      replay;
    - raw byte preservation of the complete **quiesced** base/WAL/sidecar set
      must precede any DuckDB open/checkpoint attempt;
    - a pre-existing verified archive remains a valid **conditional** restore
      source (option B), if and only if such an archive is identified.
    This is repository-backed behavior of `scripts/backup.py`; it is **not** a
    claim that `backup.py` was executed against this stand.

## Options considered and selected design

| Option | Summary | Assessment |
| --- | --- | --- |
| A. Forensic preservation + offline recovery from a copy | Inventory/copy/hash externally after reviewed quiesce; sealed master + disposable working clones only; decide disposition with data owner | **Selected.** Fail-closed; preserves rollback material; matches emptyDir risk |
| B. Restore from a verified backup | Use `verify_backup.py` + `restore.py` if an archive of these files exists | Conditional secondary path only after a real archive is identified; **no such archive is known** from supplied evidence; not a substitute for first-line raw-byte preservation of a failing open |
| C. Explicit empty-store reset | New empty paths or discarded volume contents after named data-owner acceptance of loss | Allowed only as an **explicit loss** path after A (and B if applicable); never first action |
| D. Future PVC/durable topology alignment | Enable durable volume and backup wiring so `/data` outlives pods | Separate implementation program; does not repair current WAL; out of this slice |

### Selected staged design (fail-closed sequence)

**Decision:** select option **A**, with B/C only as later gated branches.

Ordered gates (design only — not executed):

1. **Authorization gate** — separate written authorization for any runtime
   interaction. The immediate next slice may use **read-only Kubernetes
   metadata only** after that authorization. Stop if authorization is absent.
2. **Identity gate** — re-confirm pod name/UID/owner/image match the last
   known identities or document intentional drift; confirm single replica.
3. **Metadata / preservation-feasibility gate** — read-only Deployment/pod
   volume source and env for `DUCKDB_PATH`, `AGENTFLOW_USAGE_DB_PATH`,
   serving backend, control-plane store. Establish whether an exact,
   reviewed **quiesce-and-copy** mechanism can capture the complete set
   without reading database bytes yet. No file mutation. **This is the
   immediate next separately authorized slice.**
4. **Quiesce-and-capture gate** — a **later**, separately authorized,
   rollback-capable slice only after gate 3 shows a safe mechanism. Must
   quiesce writers (no continued CrashLoop open attempts) before any
   database-byte copy; produce a sealed hash-verified master of the complete
   base+WAL(+sidecar) set on host-persistent storage outside the pod; record
   deployment/env identity. Still forbids cleanup, deletion, and path
   rotation. **Stop here unless a further slice is authorized.**
5. **Offline database gate** — only on **disposable working clones** derived
   from the sealed master (never on the master or sole live original):
   attempt open/read-only validation; classify recoverable vs unrecoverable.
6. **Disposition decision** — data owner chooses: restore-from-copy,
   restore-from-known-backup (B), or explicit loss reset (C). No silent
   default to C.
7. **Runtime apply gate** — only after 1–6 and a written plan with rollback
   material (sealed master retained): controlled apply into a non-sole copy
   target, then readiness and data-continuity checks. Still separate from
   production acceptance.
8. **Future durability (D)** — after incident closure, design PVC/backup
   wiring so emptyDir discard cannot recur as the only recovery lever.

**Not selected as the next action:** pod deletion, Deployment env path
rotation, WAL-only delete, dependency re-recovery, production claim, direct
`backup.py` against the sole failing live set, or byte copy while CrashLoop
restarts continue.

## Rollback contract

### Why pod deletion cannot be rolled back for `emptyDir`

**Repository contract + historical Observed (E8, E16):** with `/data` as
`emptyDir`, volume contents are bound to the pod lifetime. Deleting the pod
(or replacing the pod such that the volume is recreated) **destroys** the
current base DB and WAL. There is no Kubernetes object that reconstitutes
those bytes. Historical recovery on 2026-08-02 intentionally used that
property to obtain a *fresh empty* volume after a prior usage-WAL crash —
that was **data discard**, acceptable only when the data-owner already
accepted loss of that emptyDir content. E16 records the task baseline
`emptyDir` (`sizeLimit: 256Mi`); E9 did not change that volume field in the
historical chain.

Therefore:

- **Rollback must be designed before mutation**, not after.
- A restorable rollback set is an **externally preserved sealed master** (or a
  previously verified backup archive) of the complete database+WAL set,
  plus saved Deployment/env identity (paths, image, volume source, control-
  plane/serving flags). Working clones used for open/replay experiments are
  **not** the rollback master.
- Without that external sealed set, any destructive action has **no rollback**
  for embedded DuckDB state on that volume.
- PVC mode (chart default when enabled) changes lifetime but still does not
  create backups; PVC alone is not a rollback plan.

### Rollback material checklist (pre-mutation)

- External directory with full file inventory and hashes of the **sealed
  master**.
- Sealed copy of every base+WAL pair intended to be mutated; disposable
  working clones created only from that master.
- Recorded Deployment name, pod UID at capture, image ID, env values for DB
  paths, volume source YAML snippet, observation timestamps.
- Explicit statement of which logical data classes are believed present
  (serving DuckDB vs control-plane-only vs usage-only), labeled Inference
  until offline open on a disposable clone proves tables.

## Layered acceptance criteria (no false green)

Each layer must pass with recorded evidence. A later layer cannot waive an
earlier failure.

| Layer | Pass condition | Required recorded evidence | False-green traps |
| --- | --- | --- | --- |
| 1. Preservation | Complete inventory + external **sealed master** copies + hashes for every candidate DB set; writers quiesced before byte copy; no mutation of live originals or of the sealed master | Inventory listing; sealed-master paths; SHA-256; quiesce mechanism reference; pod/deploy identity; authorization reference | Claiming “preserved” after only logs; hashing inside-only without external copy; copying while CrashLoop restarts continue; treating pod `exec` alone as crash-consistent; running `backup.py` open/checkpoint against the sole failing live set |
| 2. Offline database/data | **Disposable working clone** opens (or is classified unrecoverable with proof); table/class inventory for intended data classes; sealed master untouched | Offline open log on a clone; table list or explicit unrecoverable classification; no live apply yet; master hash re-check | Treating “file exists” as “data OK”; opening the sole original or the sealed master; reusing a previously opened clone as if it were still pristine |
| 3. API startup/readiness | API process starts and readiness passes against the **intended** restored/repaired data set | Pod Ready; health/ready evidence; absence of WAL replay error in startup logs | Ready on a different empty path after silent rotation |
| 4. Data continuity | Expected logical classes still present or explicitly accepted lost | Query/count/sample checks appropriate to class (embedded control-plane rows, usage rows, and/or DuckDB serving tables); CH serving checked only if in scope | Continuity claim from empty schema create-on-boot; demo seed mistaken for recovery |
| 5. Restart / pod-lifetime | Restart *within same pod* retains data when volume is emptyDir; pod replacement tested only after durability design or accepted loss | Controlled restart evidence; volume source re-confirmed | Passing container restart while still emptyDir and calling it durable |
| 6. Production claim boundary | Production remains `candidate` until separate production gates pass | Explicit non-claim; dependency/workload/clock/I/O/soak/traffic gates not silently marked pass | Elevating production because API became Ready |

**Minimum non-claims after any future successful API Ready:**

- Not a production acceptance.
- Not a soak/traffic pass.
- Not proof that external dependency recovery was incomplete (it is consumed).
- Not proof of WAL root-cause physics without forensic analysis on disposable clones.

## Exact next separate slice

**Name:** API DuckDB metadata and preservation-feasibility gate

**Type:** bounded, separately authorized read-only Kubernetes metadata /
preservation-feasibility only

**Must not include:** cleanup, WAL/base delete, path rotation, pod delete,
Deployment edit, restore into live volume, traffic, production transition,
database-byte copy, DuckDB open/checkpoint, or `backup.py` against the live
failing set.

### Gate steps (pseudocode only)

```text
IF no separate authorization for read-only Kubernetes metadata:
  STOP as BLOCKED (design complete; no live action)
ELSE:
  1) Read-only confirm context/namespace/deploy/pod UID/image
  2) Read-only capture volume source for /data and env:
       DUCKDB_PATH, AGENTFLOW_USAGE_DB_PATH,
       SERVING_BACKEND / control-plane store if present
  3) IF volume source is emptyDir OR unknown:
       treat contents as ephemeral; forbid pod delete in this gate
  4) Assess preservation feasibility only:
       - can writers be quiesced so CrashLoop open attempts stop
         before any database-byte read?
       - is there an exact, reviewed quiesce-and-copy mechanism that
         yields a crash-consistent capture of the complete
         base/WAL/sidecar set to host-persistent external storage?
       - do NOT copy database bytes in this gate
       - do NOT imply that pod exec alone is crash-consistent
       - do NOT prescribe a concrete mutating command here
  5) IF the current CrashLoop cannot be quiesced and copied without an
     additional runtime mutation (for example scaling/suspension or
     another volume-mounting mechanism) that this gate does not own:
       emit BLOCKED or PRESERVATION_PARTIAL and STOP
  6) ELSE IF a reviewed quiesce-and-copy mechanism is identified:
       record the mechanism as input to a later separately authorized
       rollback-capable capture slice; emit PRESERVATION_FEASIBLE
       (feasibility only — no capture yet)
  7) Emit result:
       PRESERVATION_FEASIBLE | PRESERVATION_PARTIAL | BLOCKED
  8) STOP — no open/repair/apply, no sealed-master creation, and no
     cleanup/deletion/path rotation in this gate
```

The actual quiesce/capture operation that creates the sealed master is a
**later** separately authorized, rollback-capable slice. That later slice
still forbids cleanup, deletion, and path rotation, and must not copy while
restart attempts continue.

### Blocker conditions

- Authorization denied or absent for the only safe path to obtain metadata
  needed for feasibility.
- Pod/UID drift without owner decision.
- No reviewed quiesce-and-copy mechanism can be established without an
  additional runtime mutation outside this gate’s ownership →
  `BLOCKED` / `PRESERVATION_PARTIAL`.
- Proposed capture would require copying while CrashLoop restarts continue.
- Proposed capture destination would be inside the same emptyDir or another
  ephemeral location.
- Any step would require deleting or renaming live DB/WAL files.

### Output artifacts expected from that future gate

- Metadata capture (volume source, env paths, identities).
- Explicit feasibility statement: whether a reviewed quiesce-and-copy
  mechanism exists, or `BLOCKED` / `PRESERVATION_PARTIAL` with reason.
- No database-byte inventory/hashes yet (those belong to the later capture
  slice that produces the sealed master).
- Explicit statement whether a verified pre-existing backup was found
  (default from current evidence: **not known / not found**).

## Open questions and data-owner decisions

1. **RPO/RTO for this stand.** Repository disaster-recovery docs refuse
   unvalidated production RPO/RTO numbers. Owner must state acceptable loss
   for embedded API state on this candidate stand before choosing option C.
2. **Which embedded records may be discarded, if any?** Possible classes if
   present: webhook queue/attempt log, alert history/runtime state, outbox/
   dead-letter, usage/session analytics, and (only if serving backend is
   DuckDB) serving tables. ClickHouse serving data is a separate store and
   was not the API WAL failure mode.
3. **Is any verified backup of the current `/data` files known outside this
   workspace?** Supplied evidence does not identify one.
4. **Confirm live volume source and env** after 2026-08-07 patches without
   assuming chart defaults or treating E16/E9 as a live re-query.
5. **Confirm live `SERVING_BACKEND` and `AGENTFLOW_CONTROLPLANE_STORE`** so
   data-continuity checks target the correct store (E16 baseline implies
   embedded default only historically).
6. **Whether future durability (PVC + backup wiring + single-writer
   enforcement already in chart) is required before any further soak** —
   separate program, not this design’s execution.
7. **Root-cause forensics** (why WAL unreplayable) only after a sealed master
   and disposable working clones exist; Colima restart remains Inference
   until then.
8. **Which reviewed quiesce-and-copy mechanism** (if any) can stop CrashLoop
   open attempts and capture bytes without unauthorized destructive mutation —
   decided only in authorized runtime slices, not by this document.

## Claim boundary for this documentation slice

| Claim | Status |
| --- | --- |
| Design document created | Yes (this file) |
| Ownership/lifetime/recovery contract established from repository + preserved evidence | Yes |
| Live preservation, cleanup, restore, or API recovery executed | **No** |
| Production readiness improved | **No** |
| External dependency recovery re-run | **No** (must remain consumed) |
| Next authorized action | Separate metadata / preservation-feasibility gate or explicit blocker if runtime interaction is not authorized |

---

*End of design. No runtime mutation was authorized or performed by this document.*
