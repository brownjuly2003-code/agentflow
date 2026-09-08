# Archived API DuckDB persistence and recovery chronology (2026-08-10 to 2026-08-23)

> **Archive metadata**
>
> - Original path: *docs/operations/api-duckdb-persistence-recovery-design.md*
> - Archived: 2026-08-27
> - Baseline commit: `ae7f38e6648fa3ca7d50496dc72225a6ca234611`
> - Baseline SHA-256: `44910a7e3cb720eed3e11fda86c1307b83a3ad4cea228df347d23e138c6c8387`
> - Reason: dated execution outcomes were interleaved with the live
>   preservation and recovery design. This body preserves the full historical
>   design-and-execution snapshot without modernization.
> - Current design:
>   [API DuckDB persistence and recovery design](../../operations/api-duckdb-persistence-recovery-design.md)
> - Content type: immutable historical design-and-execution snapshot
>
> Current truth and future authorization boundaries belong to the current
> design linked above. This archive is historical only and is not an
> executable operator runbook.
<!-- ARCHIVE BODY START -->

# API DuckDB persistence and WAL recovery design

**Date:** 2026-08-10

**Status:** `CAPABILITY_REHEARSAL_REQUIRED`; neither corrected runtime branch
is eligible or approved as an operator runbook

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
- Corrected quiesce-and-capture controls and the exact evidence required by a
  later separately authorized capability gate.

### Explicit non-goals / boundary

- No cleanup, WAL or base-file deletion, path rotation, pod deletion/replacement,
  Deployment edit, Helm upgrade, volume recreation, backup/restore execution,
  offline repair attempt, traffic, soak, clock/I/O work, Flink work, production
  transition, or push.
- E17 and E20 are the only live interactions recorded here; both were bounded
  read-only metadata gates. The design/review/documentation slices used no
  live interaction, and neither gate used workload Pod `exec`/copy or runtime
  mutation.
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
| E8 | [`.codex-grok-tasks/golden-4h-soak-api-emptydir-recovery-reinstall-20260802.md`](../../.codex-grok-tasks/golden-4h-soak-api-emptydir-recovery-reinstall-20260802.md) | **Historical** task brief (2026-08-02): prior API pod failed on `/data/agentflow_api.duckdb.wal`; task required `/data` to be verified `emptyDir` before pod delete. E17 independently confirms the current `emptyDir`; E8's destructive pod-delete precedent is not safe or authorized now |
| E9 | [`.codex-grok-tasks/golden-4h-soak-runtime-20260807-05/_fix_api_and_resume.sh`](../../.codex-grok-tasks/golden-4h-soak-runtime-20260807-05/_fix_api_and_resume.sh) | **Historical runtime patch provenance** (2026-08-07): set both `AGENTFLOW_USAGE_DB_PATH` and `DUCKDB_PATH` to `*_fresh_20260807.duckdb` when no hostPath; not the tracked chart default |
| E10 | [same pack `runtime-result.md`](../../.codex-grok-tasks/golden-4h-soak-runtime-20260807-05/runtime-result.md) | Summary emphasized usage-path fix; does not erase the dual env patch in E9 |
| E11 | [`.codex-grok-tasks/full-e2e-live-execute-20260801.md`](../../.codex-grok-tasks/full-e2e-live-execute-20260801.md) | Earlier deployment profile: ClickHouse serving + `DUCKDB_PATH=/data/agentflow.duckdb` + `AGENTFLOW_USAGE_DB_PATH=/data/agentflow_api.duckdb` on task `emptyDir` |
| E12 | [helm/agentflow/values.yaml](../../helm/agentflow/values.yaml), [templates/deployment.yaml](../../helm/agentflow/templates/deployment.yaml), [templates/pvc.yaml](../../helm/agentflow/templates/pvc.yaml), [templates/_env.tpl](../../helm/agentflow/templates/_env.tpl), [values.schema.json](../../helm/agentflow/values.schema.json) | Tracked chart ownership; defaults ≠ proved live values |
| E13 | [src/agentflow_runtime/serving/api/main.py](../../src/agentflow_runtime/serving/api/main.py), [db_pool.py](../../src/agentflow_runtime/serving/db_pool.py), [duckdb_connection.py](../../src/agentflow_runtime/serving/duckdb_connection.py) | Startup path that opens `DUCKDB_PATH` |
| E14 | [control_plane/store.py](../../src/agentflow_runtime/serving/control_plane/store.py), [embedded.py](../../src/agentflow_runtime/serving/control_plane/embedded.py), [ADR 0009](../decisions/0009-control-plane-state-and-scaling-gate.md), [ADR 0010](../decisions/0010-control-plane-externalization-postgres.md) | Conditional ownership of embedded vs PostgreSQL control-plane state |
| E15 | [docs/operations/disaster-recovery.md](disaster-recovery.md), [scripts/backup.py](../../scripts/backup.py), [verify_backup.py](../../scripts/verify_backup.py), [restore.py](../../scripts/restore.py) | Local DuckDB/config backup tooling; not proved wired to this emptyDir; not first-line preservation against a failing open (see invariant 10) |
| E16 | [`.codex-grok-tasks/checkpoint-restore-reverify-20260802-01/api-deployment.yaml`](../../.codex-grok-tasks/checkpoint-restore-reverify-20260802-01/api-deployment.yaml) | **Historical task Deployment baseline** (preserved manifest, not a live 2026-08-10 query and **not** a claim that this file was rendered by the tracked Helm chart): Deployment `agentflow-chk-restore-rv-api-20260802-01`; `DUCKDB_PATH=/data/agentflow.duckdb`; `AGENTFLOW_USAGE_DB_PATH=/data/agentflow_api.duckdb`; `AGENTFLOW_PROCESS_ROLE=all`; no explicit `AGENTFLOW_CONTROLPLANE_STORE` (application default therefore `embedded` at that baseline); `/data` is `emptyDir` with `sizeLimit: 256Mi`. Later E9 changes the two DuckDB env paths and scales the Deployment but does not change volume or process-role fields. E16 alone cannot rule out later mutation; E17 independently resolves the current live fields |
| E17 | [metadata/preservation gate `result.json`](../../.codex-grok-tasks/api-duckdb-metadata-preservation-feasibility-20260810-codex01/result.json), [`result.md`](../../.codex-grok-tasks/api-duckdb-metadata-preservation-feasibility-20260810-codex01/result.md), and [`evidence.md`](../../.codex-grok-tasks/api-duckdb-metadata-preservation-feasibility-20260810-codex01/evidence.md) | **Observed** `2026-08-10T01:18:15.0702826Z`–`01:19:42.9195636Z`; five bounded read-only Kubernetes metadata queries, all exit 0, no retries; safe fields only; no logs, `exec`, filesystem/database-byte access, or mutation |
| E18 | [`second-opinion-api-duckdb-quiesce-capture-20260810.md`](../../second-opinion-api-duckdb-quiesce-capture-20260810.md) | Local, intentionally untracked review packet written `2026-08-10T01:51:50.4624998Z`; SHA-256 `baf90a58125abfa2e1a47fe36bc8fd43d47e3d99f1548eaa01af0175e0d3e776`; records a candidate only, not an approved runbook. One bounded `claude -p` review returned exit 1 with no text; E19 is the later independent review of this unchanged packet |
| E19 | [`second-opinion-api-duckdb-quiesce-capture-grok-review-20260810.md`](../../second-opinion-api-duckdb-quiesce-capture-grok-review-20260810.md) | Local, intentionally untracked review record; SHA-256 `9ce977a4f5fc5254f07398404f3b52c96df12ffd6d0fdc8fd1e63d29c52fae22`. One read-only `local_grok_cli` session (`grok-4.5`, `019fe976-40d9-7563-ad22-aea8c9f4d8fc`) returned final verdict `ACCEPT_WITH_CHANGES`. Its first process-only response could not read files; the same session was resumed once with exact verified E18 text. No API fallback, file edit, web, or runtime action occurred |
| E20 | [capability gate `result.json`](../../.codex-grok-tasks/api-duckdb-quiesce-capability-gate-20260810-codex01/result.json), [`result.md`](../../.codex-grok-tasks/api-duckdb-quiesce-capability-gate-20260810-codex01/result.md), and [`evidence.md`](../../.codex-grok-tasks/api-duckdb-quiesce-capability-gate-20260810-codex01/evidence.md) | **Observed** `2026-08-10T02:54:35Z`–`02:59:59Z`; bounded read-only host, Kind node, and Kubernetes metadata. SHA-256: JSON `1e68ae71708dc837c39ae1be4d3751321a5436972dd3bef175728c82a8985423`, summary `bc3dddd8dfe51908cae939752f5dbfcfdf8d5399970812f934fc5520611ee0b6`, ledger `4e46065ded563a763bcca60210b5700e92c208a964b266ecce1416cb61057d0f`. Result: `CAPABILITY_REHEARSAL_REQUIRED`; no database contents read or runtime mutation |
| E21 | [`rehearse_api_duckdb_quiesce_capabilities.py`](../../scripts/rehearse_api_duckdb_quiesce_capabilities.py) and [focused unit tests](../../tests/unit/test_api_duckdb_quiesce_capability_rehearsal.py) | **Implemented, not executed** `2026-08-11`; fail-closed non-target scratch setup harness. Default plan returns `REHEARSAL_SETUP_READY_NOT_EXECUTED`, all seven checks `NOT_RUN`, and both branches ineligible. No SSH or live rehearsal ran |
| E22 | [`rehearse_api_duckdb_quiesce_capabilities.py`](../../scripts/rehearse_api_duckdb_quiesce_capabilities.py), [focused unit tests](../../tests/unit/test_api_duckdb_quiesce_capability_rehearsal.py), [archived E22 runbook](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e22-2026-08-11.md), and local [`result.json`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e22-20260811-codex01/result.json), [`result.md`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e22-20260811-codex01/result.md), [`evidence.md`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e22-20260811-codex01/evidence.md) | **Attempted once; transport blocked** `2026-08-11`. The fixed Windows invocation exited `1` after remote Bash exited `2` on CRLF-translated control lines, before any probe result. The exact scratch root was absent in the one cleanup check. Evidence SHA-256: JSON `916bd1216b3868216085bf9edd6d7f1e0ddd4fb9f3c0ee872584ebf9bcb455ea`, summary `1f82271c394fd0cee6a8429d7d2a5fdd315943ef378917f9118f0e43659c32c4`, ledger `d5a05e236cf5e6cec81a6e69d360f274ec3badcfcacc35b88fb6f2aa681ec6bf` |
| E23 | [`rehearse_api_duckdb_quiesce_capabilities.py`](../../scripts/rehearse_api_duckdb_quiesce_capabilities.py) and [focused unit tests](../../tests/unit/test_api_duckdb_quiesce_capability_rehearsal.py) | **Local transport fix verified; not executed** `2026-08-11`. Remote stdin is explicit UTF-8 bytes with no CR and stdout/stderr are decoded fail-closed. TDD RED `1 failed`; final focused gate `33 passed`. SHA-256: script `d2a8fd8715d4182cc0def0d5283c045a66eb197d979faaecfab2c1e7781faa7f`, test `74e347553e2416eb5ec5bd8cca107b097dbac06cf318c4b89cc2dcaab2ccc0bc` |
| E24 | [archived E24 runbook](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e24-2026-08-11.md) and local [`result.json`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e24-20260811-codex01/result.json), [`result.md`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e24-20260811-codex01/result.md), [`evidence.md`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e24-20260811-codex01/evidence.md) | **Executed once; `SCRATCH_REHEARSAL_BLOCKED`** `2026-08-11`. Five probes passed; descriptor visibility and metadata capability were blocked when remote `Path.write_text` rejected `newline`. Exact cleanup passed. SHA-256: JSON `389c779bd0948e41ecdd50208ca913a8dc08e48dad0e8057f3fe84755a4f1068`, summary `b915db6a8240cb7e1484fea3b836efd2eb6648a711a3e597be5eac7c5471acea`, ledger `6f0893ab2f78a132d9ae9d71f1a1d504546a9c83b17c2559e8446fa96e3cfb71` |
| E25 | [`rehearse_api_duckdb_quiesce_capabilities.py`](../../scripts/rehearse_api_duckdb_quiesce_capabilities.py) and [focused tests](../../tests/unit/test_api_duckdb_quiesce_capability_rehearsal.py) | **Local compatibility fix verified; not executed** `2026-08-11`. Both affected probes now create LF text through explicit `Path.open`; behavioral extraction tests run against a legacy `Path.write_text` signature. RED `2 failed`; final focused gate `35 passed`. SHA-256: script `d7bf34f28369b51565cf8125c62b949532b95e867f2b4c120f8472da0cc5f273`, test `a6b8f66e2e7af42b0ee2107bc57608f495baaaf22d711f7b2515c863cf7e051d` |
| E26 | [archived E26 runbook](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e26-2026-08-11.md) and local [`result.json`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e26-20260811-codex01/result.json), [`result.md`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e26-20260811-codex01/result.md), [`evidence.md`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e26-20260811-codex01/evidence.md) | **Executed once; `SCRATCH_REHEARSAL_BLOCKED`** `2026-08-11`. Six probes passed; metadata tool/ACL/xattr capability was blocked because ACL tools were absent and remote Python exposed no `os.setxattr`. Exact cleanup passed. SHA-256: JSON `fa73f2f095f094cf0210e18fd78a8940752f0c939e5f44e3efcb3aec4811d783`, summary `26dfa578d261a576b3bb7efa6488de6045a77805f83aac46ea0641fb6ed78811`, ledger `bc0bcaa6671725bbb2c51c2cc37f0a172558d322d8526d334ed058baab7c689c` |

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

**Historical provenance chain — independent of the later E17 live query.** The
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

**E17 resolves the metadata uncertainty at its observation time:** the fresh
env paths, ClickHouse serving backend, process role, and 256Mi `emptyDir` are
live. The control-plane store env is absent, so `embedded` remains the
application-default inference. File presence/content and backup existence
remain unknown because E17 intentionally performed no filesystem access.

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
| Kubernetes `/data` volume | Chart: PVC if `persistence.enabled`, else `emptyDir` | PVC: independent of pod; `emptyDir`: survives container restart in same pod, **destroyed on pod deletion** | Chart documents PVC; no automatic backup of either volume type | **Observed live in E17:** current Pod uses `emptyDir`, default medium, `sizeLimit: 256Mi`; do not delete or replace the Pod before external preservation |
| `DUCKDB_PATH` base + `.wal` | API process via `DuckDBPool` / `connect_duckdb`; on embedded control plane, also hosts webhook/alert/outbox/dead-letter tables through `query_engine._conn` | Lives on `/data` (or `:memory:` if configured) | `scripts/backup.py` can checkpoint+archive local DuckDB+WAL when pointed at openable files, but **must not** be first-line preservation against the sole failing live set (invariant 10) | **Observed** failure on `agentflow_fresh_20260807.duckdb.wal`. Base+WAL are one preservation set. Path names: E16 baseline → E9 fresh rename |
| `AGENTFLOW_USAGE_DB_PATH` base + `.wal` | `AuthManager` private DuckDB file on embedded profile; PostgreSQL adapter when `controlPlane.store=postgres` | Same volume lifetime rules as `/data` for file-backed path | Included as usage role by backup tooling when present and openable; same first-line restriction as primary | Earlier CrashLoop used `agentflow_api.duckdb.wal` (E8); historical patch moved usage to `agentflow_api_fresh_20260807.duckdb` (E9). Current remaining failure is **not** that usage WAL |
| ClickHouse serving data | External Compose/ClickHouse volume `agentflow-ch-rv-20260802-01-data` (dependency gate identities) | Outside API pod `/data` | **Not** covered by `scripts/backup.py` / disaster-recovery DuckDB runbook | Bridge recovered with backend `clickhouse` after dependency recovery (E3, E7). Independent of API WAL |
| Embedded control-plane state | Default `controlPlane.store=embedded`: tables on serving DuckDB connection (`DUCKDB_PATH`); usage/sessions on separate usage file | Per-pod / per-file | Local DuckDB backup only if files are reachable and openable | **Conditional.** E17 confirms `AGENTFLOW_CONTROLPLANE_STORE` is absent; application default, chart default, and ADR single-replica profile imply `embedded`, but this remains an inference rather than an explicit live env value |
| PostgreSQL control-plane state | Only when `controlPlane.store=postgres` + DSN secret | External to API pod | No PITR/base-backup path implemented in this repo (`docs/operations/disaster-recovery.md`) | Not proved active for this deployment from supplied evidence |
| YAML/config included by backup | Non-secret `config/` members via `scripts/backup.py` | Host/project files or ConfigMap/Secret mounts | Archived with SHA-256 manifest | Secrets (`api_keys`, `webhooks`, `tenants`) **excluded** by policy |
| YAML/config excluded / K8s-mounted | Helm mounts config ConfigMap and secret material under `/etc/agentflow/...` | Cluster objects, not DuckDB files | Not recovered from DuckDB backup archive | Re-apply from source of truth / secret manager, not from DuckDB WAL repair |

### Conditional ownership (do not invent live placement)

| Logical class | Lives in `DUCKDB_PATH` when… | Lives in usage path when… | Lives in PostgreSQL when… | Lives in ClickHouse when… | Missing runtime evidence for this pod |
| --- | --- | --- | --- | --- | --- |
| Serving entity tables / pipeline journal | `serving.backend=duckdb` (chart default) | never | never | `serving.backend=clickhouse` (historical e2e/soak profile E11; E16 task baseline also uses ClickHouse serving) | E17 confirms live `SERVING_BACKEND=clickhouse` |
| Webhook queue/log, alert history, outbox, dead-letter | embedded store on `query_engine._conn` → `DUCKDB_PATH` | never | `controlPlane.store=postgres` | never (CH rejected for this state in ADR 0010) | E17 confirms the store env is absent; embedded remains the application-default inference |
| `api_usage` / `api_sessions` | never on shared conn (ADR 0010 inventory) | embedded AuthManager file | postgres store | never | E17 confirms the live fresh usage path; store placement still follows the conditional store inference |
| Webhook registrations / alert rules files | N/A (YAML paths / ConfigMap mounts, not DuckDB) | N/A | postgres rows when externalized | N/A | Exact live registration paths not re-queried |

## Chart defaults vs historical patches vs live metadata

| Layer | What is known | What must not be assumed |
| --- | --- | --- |
| Tracked chart defaults | PVC-on by default; paths `/data/agentflow.duckdb` and `/data/agentflow_api.duckdb`; embedded control plane; DuckDB serving backend | That the stand was installed with unmodified defaults |
| Task Deployment baseline (E16, 2026-08-02) | Preserved manifest for Deployment `agentflow-chk-restore-rv-api-20260802-01`: ClickHouse serving env; both DuckDB paths at chart-like names; `AGENTFLOW_PROCESS_ROLE=all`; no explicit control-plane store env → application default `embedded`; `/data` = `emptyDir` `sizeLimit: 256Mi`. **Not** claimed to be Helm-rendered from E12 | That those exact fields remain live after later patches or unrecorded mutation |
| Historical e2e profile (2026-08-01, E11) | ClickHouse serving; both DuckDB paths on task `emptyDir`; process role `api` | That those exact filenames still apply after later patches |
| Historical emptyDir proof (2026-08-02, E8) | Prior API pod `/data` verified `emptyDir`; recovery by **pod delete** intentionally discarded volume contents | That pod delete is still safe or authorized; that emptyDir still holds without a fresh query |
| Historical fix script (2026-08-07, E9–E10) | No hostPath → `set env` both usage and primary to `*_fresh_20260807.duckdb`; scales Deployment; does **not** change volume or process-role fields relative to the E16 baseline chain; summary text focused on usage | That only usage was changed; current failure is on the primary fresh WAL; that no later unrecorded mutation occurred |
| Latest read-only verification (2026-08-10, E3–E5) | Crash on `/data/agentflow_fresh_20260807.duckdb.wal`; same pod UID as pre-dependency-recovery | Live env dump, volume source, file inventory, hashes, or existence of a backup |
| Metadata / preservation gate (2026-08-10, E17) | Same Pod UID; live fresh paths; ClickHouse serving; process role `all`; 256Mi `emptyDir`; no existing helper/init/ephemeral path; `PRESERVATION_PARTIAL` | File inventory/content/hashes, a verified backup, or a reviewed quiesce-and-copy mechanism |

**Still unknown after E17:** file listing under `/data`, file sizes/mtimes/
hashes, whether the base DB exists beside the WAL, whether any external backup
of those files exists, and an exact reviewed quiesce-and-copy mechanism.

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

## Metadata and preservation-feasibility gate outcome — 2026-08-10

The separately authorized read-only metadata gate defined above was executed
once against `deproject-mac`, context
`kind-agentflow-reverify-ed03fc47`, namespace `agentflow`. E17 is the
sanitized evidence pack.

| Gate | Result | Decisive evidence |
| --- | --- | --- |
| Metadata | `METADATA_PASS` | Live Deployment → ReplicaSet → Pod ownership chain matches preserved identity; live env and `/data` source are now confirmed |
| Preservation feasibility | `PRESERVATION_PARTIAL` | `QUIESCE_AND_COPY_MECHANISM_NOT_ESTABLISHED` |
| Capture | Not authorized and not performed | No database-byte inventory, copy, open, checkpoint, or sealed master |
| Production | `candidate` (unchanged) | This gate is not readiness, continuity, soak, traffic, or production acceptance |

### Live metadata observed

- Deployment `agentflow-chk-restore-rv-api-20260802-01` UID
  `a2f14325-e1e5-4122-9d08-74c73a573d5a`, generation 4, desired/updated 1,
  ready/available 0; ReplicaSet revision 2 and hash `59489dd45c`.
- The sole matching Pod remains
  `agentflow-chk-restore-rv-api-20260802-01-59489dd45c-kk8tf`, UID
  `c9d26829-c57f-4550-a86f-cdcc41e719fd`: no drift from E3. It was
  `Ready=False`, `CrashLoopBackOff`, restart count 90; last observed
  termination was `Error`, exit 3, at `2026-08-10T01:16:26Z`.
- `DUCKDB_PATH=/data/agentflow_fresh_20260807.duckdb`,
  `AGENTFLOW_USAGE_DB_PATH=/data/agentflow_api_fresh_20260807.duckdb`,
  `SERVING_BACKEND=clickhouse`, and `AGENTFLOW_PROCESS_ROLE=all` are live.
  `AGENTFLOW_CONTROLPLANE_STORE` is absent; `embedded` remains an
  application-default **Inference**, not an explicit env value.
- `/data` is a read-write `emptyDir` named `data`, default medium,
  `sizeLimit: 256Mi`; its lifetime is the current Pod.
- `restartPolicy=Always`. The Pod has one regular container, zero init
  containers, zero ephemeral containers, no declared shared process
  namespace, and no other existing container that mounts `/data`.

### Feasibility decision and boundary

The metadata closes the former live identity/volume/env gaps but does not
provide a reviewed crash-consistent capture path. The only existing `/data`
consumer is the repeatedly starting API process, while Pod replacement would
destroy this `emptyDir`. A bounded repository/evidence search found no
previously reviewed exact helper, signal, node-runtime, or kubelet-volume
procedure that both quiesces open attempts and copies the complete
base/WAL/sidecar set to host-persistent external storage.

Adding a helper or ephemeral container, changing/scaling the workload, or
controlling the process from the node would be an additional runtime mutation
outside this gate. Consequently the gate stops at `PRESERVATION_PARTIAL` with
`QUIESCE_AND_COPY_MECHANISM_NOT_ESTABLISHED`. It did not probe such mechanisms
live, list database files, query logs, or read/copy database bytes. No verified
backup of the current set is known or identified; no runtime backup search was
performed.

Any continuation must be a new, separately authorized slice: first design and
review an exact rollback-capable quiesce-and-capture mechanism, then authorize
runtime capture independently. Pod delete/replacement, path rotation, cleanup,
or copying while restart attempts continue remain forbidden.

### Artifact integrity

| Artifact | SHA-256 |
| --- | --- |
| `result.json` | `e6e98176c68541e44966fd1b24d88a33f3305f3714138d1b64032371b78d195b` |
| `result.md` | `d7c3f43f60ec605797ca2e6e4cef21f5c80e95c28c36a7cee3e0a2f0be6eb10f` |
| `evidence.md` | `8a4f0e6d34698c7dc9ac5eaeb72a197a7563606bb1b966d7b2ed2b786f1322a4` |

## Quiesce-and-capture design review hold — 2026-08-10

A later local-only slice investigated one possible emergency preservation
mechanism but did **not** approve or execute it. E18 contains the exact
adversarial review request. It must not be treated as an operator runbook.

### Primary-source findings

| Source | What it establishes | What it does not establish |
| --- | --- | --- |
| [Kubernetes volumes / `emptyDir`](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir) | `emptyDir` survives a container crash and is deleted when its Pod is removed from the node | Safety of copying files during DuckDB replay |
| [Kubernetes Pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/) | Kubelet performs restart-policy restarts; stopping/restarting kubelet does not itself stop local Pod containers; a long outage can lead to node-unhealthy handling and eviction | A stand-specific safe kubelet-stop duration |
| [Kubernetes 1.32 controller-manager reference](https://v1-32.docs.kubernetes.io/docs/reference/command-line-tools-reference/kube-controller-manager/) | Default `node-monitor-grace-period` is 50 seconds | The live flag value or workload tolerations on this stand |
| [Kubernetes EphemeralContainer API](https://kubernetes.io/docs/reference/kubernetes-api/workload-resources/pod-v1/#EphemeralContainer) | Ephemeral containers may declare volume mounts and a target container | Runtime support, cross-restart PID visibility, admission, or safe quiescence here |
| [Docker `cp`](https://docs.docker.com/reference/cli/docker/container/cp/) | A file can be copied from a container filesystem to the local machine | Crash consistency of a file being concurrently changed |
| [Kind node-image boundary](https://kind.sigs.k8s.io/docs/design/node-image/) | Kind explicitly warns users not to depend on node-image internals | Stability of kubelet host paths or systemd details across node images |
| [systemd `--on-active` implementation](https://github.com/systemd/systemd/blob/main/src/run/run.c) | `systemd-run` supports a delayed transient timer | Availability and exact behavior on the live Kind node without a capability check |

### Candidate considered, not selected

The candidate was to stop only `kubelet.service` under an independent
auto-start watchdog, wait fail-closed for the CrashLoop container to exit,
prove no running API task or open file descriptor below the exact `emptyDir`,
flush pending filesystem writes, create a read-only uncompressed tar in node
staging, resume kubelet, and then copy/hash that sealed staging archive to the
macOS host. No command implementing this sequence was written or executed.

### Independent Grok verdict

E19 records the single independent content review. The read-only
`local_grok_cli` session returned `ACCEPT_WITH_CHANGES`; it approved neither
execution nor an operator runbook. The preservation skeleton is viable only
after these design defects are corrected and reverified:

1. The fixed 75-second watchdog exceeds the documented Kubernetes 1.32
   default 50-second node-monitor grace. A corrected design must prove a live
   safe budget and require
   `stop + wait + sync + tar + kubelet-active < safe budget < watchdog` with
   explicit margin, or reject kubelet-stop.
2. Stopping kubelet on a single-node Kind control-plane has the widest blast
   radius. It must be last-resort only, with an explicit outage model and
   aborts on Node or Pod lifecycle drift.
3. The required base/WAL/sidecar inventory is undefined. Pre-quiesce exact
   paths and post-tar member/size checks must prove completeness before any
   artifact can be promoted.
4. Two zero-task samples do not prevent task or kubelet reactivation during
   tar. The archive must be invalidated on any possible writer return, and the
   file-descriptor proof must work across the exact host path or relevant
   mount namespace.
5. Tar success, timeout, disk-full, immutable hash, `.partial`, staging
   retention, rollback, and watchdog-cancellation rules need one fail-closed
   contract. Success means only a sealed filesystem-level artifact, not a
   replayable DuckDB database.

The reviewer classified live grace, tolerations, kubelet root, exact
`emptyDir` path, systemd behavior, runtime APIs, tools, space, and host-copy
path as capability evidence for a later separately authorized read-only
probe, not as facts the design may assume. An ephemeral container is not a
quiesce mechanism. Containerd task-pause has a narrower blast radius for a
running task, but its availability, flush behavior, and guaranteed resume are
also unproved; it does not apply while no task exists.

### Corrected design disposition

The E18 sequence is historical review input, not the corrected mechanism.
The design below closes the E19 design findings without treating any unknown
live capability as present. Its status is
`DESIGN_CORRECTED_RUNTIME_BLOCKED`; E17 remains `METADATA_PASS` /
`PRESERVATION_PARTIAL` until a later authorized capability gate proves one
branch eligible and a still-later runtime slice performs capture.

## Corrected quiesce-and-capture design — 2026-08-10

This section is a fail-closed technical design, not an operator runbook. It
contains no executable commands and authorizes no runtime interaction. Its
only possible success claim is an immutable, externally verified archive of
quiescent on-disk bytes. It cannot claim that DuckDB can replay, open, or
recover those bytes.

<!-- E19_CORRECTED_DESIGN_START -->

### C01 — Branch selection and state machine

Exactly one branch may be selected from fresh evidence. An attempt must not
switch branches after its first quiescing action:

| Branch | Eligibility | Quiescence proof | Automatic recovery action |
| --- | --- | --- | --- |
| `PAUSED_TASK` | The exact API container task exists; pause/resume support, complete cgroup freeze, task identity, kubelet probe budget, and runtime monitoring are proved | The exact task and all its threads remain frozen; only its recorded pre-existing descriptors may remain open; no other writer exists | An independent watchdog resumes the exact task |
| `KUBELET_GAP` | No target task exists; live node/Pod policy yields a safe timing envelope; the independent watchdog and exact source mount are proved | Kubelet remains inactive, the target task remains absent, and no process has an open descriptor on the source mount | An independent watchdog starts kubelet |
| `BLOCKED` | Either branch has an unknown or failed prerequisite | None | No quiescing action is allowed |

`PAUSED_TASK` is narrower than stopping kubelet, but it is ineligible if a
kubelet probe can kill or replace the frozen task inside the proved window.
If the task exits or changes identity before pause completes, the attempt
aborts; it does not fall through to `KUBELET_GAP`. `KUBELET_GAP` is last
resort on this single-node control-plane and is ineligible unless every C03
inequality passes with margin.

An ephemeral container is never a quiescence branch. It can only add another
volume reader while kubelet remains free to restart the API process. No helper
is injected by this design.

The only allowed state progression is:

```text
PRECHECK -> RECOVERY_ARMED -> QUIESCED -> SOURCE_STABLE -> ARCHIVE_BUILDING
         -> NODE_CANDIDATE_SEALED -> RUNTIME_RESUMED -> NODE_VERIFIED
         -> HOST_MASTER_VERIFIED -> CAPTURE_ONLY_PASS
```

Any missing proof, timeout, identity change, monitor gap, or unexpected state
transitions to `ABORT_AND_RESUME`; it never skips forward or promotes an
incomplete artifact.

### C02 — Capability evidence contract

Every input below is **Unknown** until a separately authorized, timestamped
evidence pack proves it. Unknown, stale, ambiguous, or contradictory evidence
makes the affected branch `BLOCKED`.

| Input | Required evidence | Fail-closed rule |
| --- | --- | --- |
| `I01_CLUSTER_POLICY` | Live node-monitor grace, taint/eviction behavior, Pod tolerations, probe timing, and single-node control-plane policy | No default value may be substituted; no eligible timing envelope means no quiescence |
| `I02_IDENTITY` | Deployment/ReplicaSet/Pod UID, deletion timestamp, node, image digest, container ID, task ID, and exact single-replica ownership | Any drift, duplicate target, deletion intent, or incomplete identity blocks the attempt |
| `I03_MOUNT` | Kubelet root, exact Pod-UID/volume-derived `emptyDir` source, mount ID/device, mount provenance, namespace visibility, and source/destination separation | Fuzzy filename search, multiple matches, symlink escape, or unsupported visibility blocks the attempt |
| `I04_RUNTIME` | Exact pause/resume semantics, cgroup-wide frozen-state proof, task events, and host visibility of processes/descriptors | `PAUSED_TASK` is blocked unless pause and guaranteed recovery can both be observed |
| `I05_WATCHDOG` | Recovery timer independence, monotonic activation, exact target action, liveness, firing evidence, and verified cancellation | Neither branch may quiesce before its branch-specific watchdog is proved armed |
| `I06_TOOLS` | Exact flush, tar, archive-list, hash, permission, and filesystem-sync tool versions and required semantics | Missing or incompatible behavior blocks archive creation |
| `I07_INVENTORY_SPACE` | Source metadata inventory, archive-size upper bound, free node staging space, and free host space including explicit margin | No optimistic compression or sparse assumption may replace a proved upper bound |
| `I08_HOST_DESTINATION` | Empty unique destination, durable filesystem, same-directory atomic rename, sync semantics, and retention ownership | An existing, ephemeral, ambiguous, or non-durable destination blocks host promotion |
| `I09_TIME_SOURCE` | Monotonic clock, resolution, command-start overhead, monitor delay, and recovery-action latency | Unbounded timing or wall-clock-only accounting blocks both branches |

The future capability gate may inspect only the metadata required above under
its own explicit authorization. It may not pause a task, stop kubelet, inject
a helper, open DuckDB, hash/copy database bytes, or create a capture.
If an input such as pause/resume or watchdog behavior requires an active
rehearsal rather than inspection of existing evidence, the read-only gate must
emit `CAPABILITY_REHEARSAL_REQUIRED`; it may not upgrade that input from
Unknown. Any isolated rehearsal is another separately authorized slice and
must not target this Pod or its volume.

### C03 — Timing envelope

The design removes E18's fixed 75-second watchdog and 15-second wait. The
future evidence pack must define these branch-specific values before any
quiescing action:

- `T_risk`: earliest proved unsafe transition. For `PAUSED_TASK`, this
  includes kubelet probe kill/restart. For `KUBELET_GAP`, it includes Node
  condition, taint/eviction, and control-plane policy boundaries.
- `M`: explicit positive margin covering clock resolution, scheduling jitter,
  monitor delay, command startup, and measured recovery-action latency.
- `T_safe = T_risk - M`.
- `T_work_limit`: hard monotonic limit from the first quiescing action through
  successful task resume or kubelet-active proof. It includes quiescence,
  stable inventory, mount flush, archive creation, candidate seal, and
  recovery.
- `T_watchdog`: monotonic deadline at which the already armed independent
  watchdog performs the branch-specific recovery action.

Both branches require:

```text
0 < T_work_limit < T_watchdog < T_safe
```

Each stage has its own sub-deadline and their worst-case sum must not exceed
`T_work_limit`. Node-candidate hashing and host copy occur only after runtime
resumption, so they consume no quiescence budget. If `T_risk`, `M`, any stage
bound, or the inequality cannot be proved, the branch is ineligible. A timeout
triggers C11 once; it never extends the deadline or retries the same attempt.

### C04 — Identity and mount provenance

Before arming recovery, the evidence must pin the exact owner chain, Pod UID,
node, image digest, container/task identity, volume name/type/size limit, and
both configured DuckDB paths. The Pod must have no deletion timestamp and no
second `/data` consumer.

The source path must be derived from the pinned Pod UID and volume name, then
matched to one exact mount ID and device through mount metadata. It must be
inside the proved kubelet root, resolve without symlink escape, and correspond
to the live Pod mount. The staging and host destinations must be empty, unique,
outside that mount, and must not alias it through bind mounts, links, or path
normalization. Kind node-image internals remain unsupported: any path mismatch
or ambiguous match blocks the design rather than falling back to a search for
`*.duckdb`.

### C05 — Complete inventory contract

A provisional metadata-only inventory is captured before quiescence for drift
detection. After C06 proves quiescence, two full source-metadata inventories
separated by a proved sample interval must match exactly. Each record contains
relative path, object type, apparent size, allocated blocks, mtime, inode,
device, ownership, mode, symlink target, hard-link group, and a non-secret
digest of xattr/ACL metadata.

The authoritative preservation set is the entire exact source mount, not a
filename allowlist:

1. The configured primary base path and the observed failing WAL path must be
   present as regular files. Missing or unexpectedly empty members block the
   attempt rather than creating replacements.
2. The configured usage base/WAL paths are recorded as present or absent;
   every member that exists is included. Absence is evidence, never a reason
   to create a file during capture.
3. Every other sidecar, temporary, hidden, directory, and unknown entry below
   the source is included. Unsupported special files or a path escaping the
   source block the attempt.
4. The archive never dereferences symlinks and never crosses a filesystem.
5. After sealing, the archive member manifest must match the stable source
   inventory one-for-one. Compare size for regular files, symlink target for
   symlinks, hard-link relationships, and the applicable ownership/mode/
   xattr/ACL metadata for each object type. Missing, duplicate, truncated, or
   unexpected members invalidate the candidate.

This all-entry rule closes the base/WAL/sidecar completeness gap without
inventing DuckDB sidecar naming conventions.

### C06 — Continuous quiescence and descriptor proof

Quiescence must remain continuously observable from its first proof until the
archive closes and the node candidate is sealed.

- `KUBELET_GAP` requires kubelet inactive, no target containerd task, and zero
  open descriptors by any node-visible process on the exact source mount.
- `PAUSED_TASK` requires the pinned task and every thread in its cgroup to
  remain frozen. Only that task's recorded, stable descriptors may remain
  open; all other processes must have zero descriptors on the source mount.
- Descriptor inspection must cover the host PID view and relevant mount
  namespaces and compare resolved mount IDs/inodes, not only path strings.
  Incomplete namespace visibility is a blocker, not a zero-FD result.
- An independent monitor observes kubelet state, watchdog state, target task
  identity/state, cgroup frozen state when applicable, the pinned Pod UID,
  deletion timestamp and owner state, mount identity, and runtime events
  throughout archive creation. Monitor loss or any writer-possible transition
  invalidates the attempt immediately.
- Once the branch-specific state and descriptor proof hold, the exact source
  filesystem is flushed. Only after a successful flush are the two C05 stable
  inventories taken while the monitor remains green. Flush failure, mount
  drift, or a subsequent inventory/runtime-state change triggers C11.

Two samples alone are never treated as continuous proof.

### C07 — Node archive and seal

The archive is created in a unique empty node staging directory outside the
source mount. Space must exceed the inventory-derived uncompressed upper bound
plus the proved margin on both node and host. The archive preserves numeric
ownership, sparse layout, xattrs, ACLs, and link metadata, does not dereference
symlinks, and is restricted to the one proved source filesystem.

Archive output begins with a `.building` identity under a hard C03 deadline.
Timeout, nonzero exit, disk-full, archive-time omission/change warning, or
monitor event stops the writer and labels the artifact `.partial`; a partial
artifact is never hashed, renamed as a candidate, or promoted. Structural and
member-manifest comparison occurs after runtime resumption under C09.

Only after a clean archive close and green continuous monitor may the artifact
and staging directory be flushed, made non-writable, and atomically renamed to
`.sealed-candidate`. The sealed candidate is now independent of resumed live
writers. Hashing and structural/member verification intentionally wait until
after C08, reducing the quiescence window.

### C08 — Runtime resumption and watchdog disposition

Runtime recovery precedes candidate verification and host copy:

- `PAUSED_TASK` resumes the exact pinned task and proves that the cgroup is no
  longer frozen or records its normal exit/restart transition.
- `KUBELET_GAP` starts kubelet and proves the service active.

The watchdog is cancelled only after the normal recovery action is proved.
Cancellation must itself be verified. A fired, missing, or indeterminate
watchdog, failed task resume, or failed kubelet-active proof makes the overall
attempt failed and stops further promotion. The sealed node candidate, if one
exists, is retained as labelled evidence but is not called a master.

After recovery, require the same Pod UID with no deletion timestamp and the
Node to return Ready. Failure to restore the runtime boundary is an incident,
not permission to delete/replace the Pod or modify database files.

### C09 — Node verification and host-master promotion

Only after C08 passes may the non-writable node candidate be SHA-256 hashed,
structurally opened as an archive, and compared against the C05 manifest. The
node candidate remains immutable. Validation never opens DuckDB.

Host copy writes to a unique `.incoming` path. After a complete copy, flush
the file and destination directory, compare host and node SHA-256, verify the
same archive/member manifest, make the host artifact non-writable, then use a
proved same-directory atomic rename to its final master name. A failed copy,
flush, hash, manifest, permission, or rename leaves only a labelled host
`.partial`; it is never retried or promoted automatically. The sealed node
candidate is retained until a separate cleanup decision.

The evidence manifest records identities, selected branch, capability-pack
identity, monotonic stage timings, watchdog/monitor results, source inventory,
archive member inventory, node and host hashes, resumption proof, and every
non-secret command result. It excludes credentials and database contents.

### C10 — Claim boundary

`CAPTURE_ONLY_PASS` means only that an immutable host master reproduces the
quiescent filesystem bytes represented by the complete inventory. It is not
proof that DuckDB can replay the WAL, that any logical table is recoverable,
that the API is Ready, or that production gates pass. Every database open,
repair, restore, or data-continuity test remains an offline later slice on a
new disposable clone derived from the master.

### C11 — Abort and rollback contract

| Failure boundary | Mandatory response | Artifact disposition |
| --- | --- | --- |
| Precondition, identity, mount, space, or timing proof fails | Do not quiesce; emit `BLOCKED` | No artifact |
| Pause/stop or first quiescence proof fails | Perform the already armed recovery action; verify runtime boundary; stop | No candidate; any scratch is `.partial` |
| Monitor, task, kubelet, mount, inventory, flush, tar, or deadline changes during archive | Stop archive once; perform recovery; never continue the archive | `.building` becomes labelled `.partial`; never hash or promote |
| Watchdog fires or its state is indeterminate | Treat capture as invalid; prove recovery action and stop | Retain only labelled partial/evidence |
| Normal task resume or kubelet-active proof fails | Escalate runtime incident; do not perform host promotion or destructive recovery | Retain a sealed node candidate only as non-master evidence |
| Node verification or host copy/hash/manifest/promotion fails | Leave live runtime untouched; stop without automatic retry | Retain sealed node candidate; host output remains `.partial` |
| Full capture succeeds | Stop before DuckDB open, cleanup, repair, restore, or Pod change | Retain both node candidate and immutable host master |

Every rollback leaves the live DB/WAL bytes untouched. No branch may delete,
rename, checkpoint, open, repair, restore, or replace live data or the Pod.

### E19 finding-to-control mapping

| Finding | E19 concern | Corrected controls | Design disposition |
| --- | --- | --- | --- |
| `F01` | Fixed watchdog exceeds default grace | C02, C03, C11 | Closed: no constants; failed inequality blocks the branch |
| `F02` | Single-node kubelet blast radius | C01, C02, C03, C08, C11 | Closed: kubelet is last resort with explicit policy/timing/resumption proof |
| `F03` | Base/WAL/sidecar completeness undefined | C05, C07, C09 | Closed: whole-mount stable inventory and exact archive-manifest equality |
| `F04` | Two samples do not prevent writer return | C03, C06, C07, C11 | Closed: continuous monitor through immutable candidate seal |
| `F05` | Host path-only FD scan can miss namespaces | C02, C04, C06 | Closed: mount-ID/inode proof across host PID and relevant mount namespaces |
| `F06` | Preservation is not DuckDB recovery | C10 | Closed: capture-only filesystem claim |
| `F07` | Kind node internals and fuzzy paths are unsafe | C02, C04 | Closed: exact UID/volume/mount provenance or `BLOCKED` |
| `F08` | Tar, timeout, partial, hash, and promotion gaps | C02, C03, C07, C09, C11 | Closed: bounded build, immutable candidate, post-resume verification, no partial promotion |
| `F09` | Preconditions and rollback incomplete | C01–C09, C11 | Closed: one fail-closed state machine and recovery-first abort matrix |
| `F10` | Live capabilities remain unknown | C02 | Deferred fail-closed: every Unknown keeps the affected branch ineligible |

### Corrected design result and next gate

All ten E19 findings map to explicit controls. `F01`–`F09` are closed at the
design level; `F10` deliberately remains an evidence dependency rather than
an assumed fact. The corrected status is `DESIGN_CORRECTED_RUNTIME_BLOCKED`,
not runbook approval and not `PRESERVATION_FEASIBLE`.

At the close of the corrected-design slice, the next possible slice required
separate authorization for a bounded, read-only **API DuckDB quiesce
capability gate** that records C02 inputs and evaluates C01/C03 branch
eligibility. It had to stop at `PAUSED_TASK_ELIGIBLE`,
`KUBELET_GAP_ELIGIBLE`, `CAPABILITY_REHEARSAL_REQUIRED`, or
`QUIESCE_AND_COPY_MECHANISM_NOT_ESTABLISHED`; it could not quiesce, copy/hash
database bytes, create an archive, or mutate the runtime. E20 below records
the later separately authorized read-only gate; it does not retroactively
expand the corrected-design slice.

Only after one branch is proved eligible may a separate tracked operator
runbook be written and reviewed. Runtime preflight, pause/stop, helper
injection, filesystem/database-byte access or copy, capture, cleanup, restore,
traffic, production transition, and push remain separately unauthorized.

<!-- E19_CORRECTED_DESIGN_END -->

## Quiesce capability gate outcome — 2026-08-10

The separately authorized read-only C02/C03 gate ran once against
`deproject-mac`, Kubernetes context `kind-agentflow-reverify-ed03fc47`, and
namespace `agentflow`. E20 is the sanitized evidence pack. It records 12 SSH
invocations (10 exit zero and two bounded command-shape exits), 10 Kubernetes
read calls, no raw retries, two narrowed query corrections, and one Docker
context method change. The workload identity remained stable throughout the
observation.

| Gate field | Result |
| --- | --- |
| Preservation status | `PRESERVATION_PARTIAL` |
| C01 classification | `CAPABILITY_REHEARSAL_REQUIRED` |
| `PAUSED_TASK` eligible | **No** |
| `KUBELET_GAP` eligible | **No** |
| Capture authorized or performed | **No** |
| Production | `candidate` (unchanged) |

### Capability input disposition

| Input | E20 status | Decisive constraint |
| --- | --- | --- |
| I01 cluster policy | `UNKNOWN_TIMING_ENVELOPE` | The selected live controller flags are absent; C02 forbids substituting documented defaults, so `T_risk` and `T_safe` remain Unknown |
| I02 identity | `PASS_POINT_IN_TIME` | Deployment, ReplicaSet, Pod, Node, image, and volume identities did not drift during the gate |
| I03 mount | `PARTIAL_BLOCKED` | The exact UID-derived source exists, but kubelet root is not explicit and the cross-namespace FD scan exited 2; this is not zero-descriptor proof |
| I04 runtime | `REHEARSAL_REQUIRED` | containerd pause/resume help exists, but the target container was exited, no matching task existed, and behavior is unproved |
| I05 watchdog | `REHEARSAL_REQUIRED` | systemd timer flags exist, but independent monotonic firing, recovery action, and cancellation are unproved |
| I06 tools | `PARTIAL_BLOCKED` | Archive/flush/hash tools exist; `getfacl` and `getfattr` are absent and no C05-compatible alternative is proved |
| I07 inventory/space | `PARTIAL` | Four regular files total 33,836 apparent and 40,960 allocated bytes, but the point-in-time inventory is neither quiesced nor a proved archive upper bound |
| I08 host destination | `BLOCKED_DESTINATION_ABSENT_AND_UNREHEARSED` | `/Users/julia/agentflow-preservation` is absent; no atomic rename or directory-sync behavior was tested |
| I09 time source | `REHEARSAL_REQUIRED` | The host monotonic clock is suitable; node timing, command overhead, monitoring delay, recovery latency, and the C03 inequality remain unbounded |

The exact source observed was
`/var/lib/kubelet/pods/c9d26829-c57f-4550-a86f-cdcc41e719fd/volumes/kubernetes.io~empty-dir/data`
on ext4 `/var`. The four-name base/WAL inventory is provisional metadata only:
no file content was opened, hashed, copied, checkpointed, or repaired. The API
remained `CrashLoopBackOff`, Ready false, restart count 109; at the runtime
query the CRI container was exited and no matching containerd task existed.

### Decision and next authorization boundary

Neither corrected branch satisfies C02/C03. `PAUSED_TASK` lacks a live task
and behavioral/timing proof. `KUBELET_GAP` lacks a proved timing envelope,
independent watchdog, descriptor proof, complete metadata tooling, and durable
host-promotion behavior. The only valid gate result is therefore
`CAPABILITY_REHEARSAL_REQUIRED`, not an eligible branch and not runbook
approval.

No workload Pod exec/logs, pause/resume, signal, scale, restart, kubelet
stop/start, timer/helper/archive/destination creation, database-byte access,
capture, cleanup, restore, traffic, production transition, or push occurred.
A later isolated rehearsal or setup is a new separately authorized slice. It
must use non-target scratch state and must not operate on this Pod or its
volume. Until such evidence passes, no operator runbook or capture is
approved.

### E20 artifact integrity

| Artifact | SHA-256 |
| --- | --- |
| `result.json` | `1e68ae71708dc837c39ae1be4d3751321a5436972dd3bef175728c82a8985423` |
| `result.md` | `bc3dddd8dfe51908cae939752f5dbfcfdf8d5399970812f934fc5520611ee0b6` |
| `evidence.md` | `4e46065ded563a763bcca60210b5700e92c208a964b266ecce1416cb61057d0f` |

## Non-target rehearsal harness setup — 2026-08-11

The separately authorized setup slice added E21 without changing E20's
runtime classification. The Python 3.11+ standard-library harness defaults to
a deterministic non-mutating plan and requires `--execute`, the exact
`NON_TARGET_SCRATCH_REHEARSAL_ONLY` acknowledgement, a conservative run ID,
and an exact new path below
`/tmp/agentflow-api-duckdb-capability-rehearsal/` before its one guarded SSH
call is reachable. Unsafe, traversal-prone, base, target, and out-of-prefix
paths fail before subprocess execution. Remote output uses strict
duplicate-key and exact claim-boundary validation with no retry.

The remote payload in this setup slice only creates and removes a sentinel-
guarded empty scratch directory. It deliberately leaves timing, pause/resume,
watchdog, descriptor, metadata, atomic-rename, and sync checks `NOT_RUN`; it
does not establish I01–I09 evidence or make either branch eligible. The
default CLI plan ran locally once. No `--execute`, SSH, Docker, Kubernetes,
containerd, systemd, target Pod/volume access, database-byte access, capture,
repair, recovery, traffic, production transition, or push occurred.

One `local_grok_cli` implementation attempt was cancelled at a disallowed
compound hash command before file changes. The single narrowed follow-up
(`grok-4.5`, actual `grok-4.5-build`) created both scoped files but produced no
final log and was terminated after the six-poll budget. Codex then verified
the protected hashes, reviewed the complete files, tightened the remote schema
fail-closed after a `3 failed, 21 passed` RED, and obtained `24 passed` plus
Ruff lint/format and bytecode-compile passes. No Grok process remains active.

## Non-target scratch probe implementation — 2026-08-11

E22 extends the E21 guard with seven actual scratch-only probes. The embedded
Python probe measures monotonic resolution and process-launch overhead; proves
`SIGSTOP`/stable-counter/`SIGCONT` behavior for its own scratch writer; checks
an independent scratch watchdog's fire and cancellation paths; locates one
known open scratch descriptor through `/proc/self/fd` or `lsof`; exercises
mode, xattr, and available ACL tools; verifies same-directory `os.replace`;
and performs file plus directory `fsync` around promotion.

Every probe catches its own bounded failure as `BLOCKED`; metadata may be
`PARTIAL` when only a subset of mode/xattr/ACL behavior is available. Remote
JSON must contain exactly the seven result and evidence records, rejects
duplicate or extra keys, and never accepts `NOT_RUN` after execution. The
cleanup path requires the exact normalized root, run ID, sentinel existence,
and sentinel content before removing only that run's `work` directory.

These probes characterize non-target host scratch primitives only. Even if
all seven later report `PASS`, they do not prove containerd/cgroup behavior,
cross-namespace target descriptor coverage, target watchdog recovery,
`T_safe`, I04/I05/I09, or either corrected branch. Default plan mode ran once
locally and remained `REHEARSAL_SETUP_READY_NOT_EXECUTED` with all checks
`NOT_RUN`. No `--execute`, SSH, scratch mutation, target access, or evidence
pack was produced in this implementation slice.

TDD RED was `4 failed, 28 passed`; one test-scope correction moved the suite
from `1 failed, 31 passed` to final `32 passed`. Ruff lint/format, outer Python
compile, embedded remote-source compile, default CLI, and scoped diff checks
passed. No delegation or background writer ran.

### Exact next-session execution contract

This historical section records the pre-execution E22 contract. E22 is now
consumed; the
[archived E22 runbook](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e22-2026-08-11.md)
preserves its exact recipe, while the
[current guide](api-duckdb-non-target-scratch-rehearsal-runbook.md) requires a
new identity and separate authorization. The E22 contract fixed one run ID,
scratch root, evidence directory, acknowledgement, implementation hashes, command
shape, result classifications, cleanup proof, and stop conditions. It also
forbids PowerShell stdout redirection so the raw JSON is not silently
re-encoded, and forbids a second identity or retry after any timeout, nonzero,
schema failure, `BLOCKED` result, or cleanup uncertainty.

The runbook does not itself authorize execution. A latest user message must
explicitly continue or authorize that isolated non-target run. Target access
and every later capture/recovery action remain separately unauthorized.

## Non-target scratch rehearsal attempt — 2026-08-11

The latest explicit continuation authorized the runbook's fixed E22 identity.
Its preflight passed: the protected script and focused-test SHA-256 values
matched, the tracked tree was clean, the reserved local evidence directory was
absent, and no matching E22 process was active.

The one allowed invocation was consumed and classified
`SCRATCH_REHEARSAL_TRANSPORT_BLOCKED`. The local harness exited `1` after
remote Bash exited `2` while parsing carriage-return-terminated `set`,
`umask`, blank, and `case` lines. No stdout JSON or probe evidence existed.
The sender uses `subprocess.run(..., input=REMOTE_PAYLOAD, text=True,
encoding="utf-8")`; on Windows this text stdin boundary translated LF to
CRLF before Bash parsed the payload.

The one permitted read-only cleanup check exited `0`, proving the exact
per-run root absent. No retry, alternate identity, manual cleanup, target
fallback, or Grok run occurred. The local evidence pack passed strict unique
JSON, UTF-8/LF, cross-artifact, and SHA-256 checks. All seven authoritative
capability results therefore remain `NOT_RUN`; `PAUSED_TASK` and
`KUBELET_GAP` remain ineligible, and the runtime status remains
`CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`.

The next separate candidate is a local TDD transport fix that sends the
remote payload as explicit LF bytes and covers the real subprocess boundary.
That slice must not execute a live rehearsal. A later live attempt requires a
new explicit authorization and a new conservative identity.

## Windows LF transport correction — 2026-08-11

E23 closes the local transport defect without reusing the consumed E22
identity. `execute_rehearsal_setup` now encodes `REMOTE_PAYLOAD` as UTF-8
bytes and leaves subprocess text mode disabled, so Windows cannot translate
LF to CRLF. A bounded decoder normalizes real byte stdout/stderr while
preserving compatibility with injected test runners and replacement behavior
for invalid UTF-8 diagnostics.

The regression test captures the actual runner kwargs, requires a byte input
equal to `REMOTE_PAYLOAD.encode("utf-8")`, rejects every CR byte, and proves
byte stdout still reaches strict JSON validation. Its RED result was one
failure on the former string input; the final focused suite passed `33/33`.
Ruff lint/format, compile, default non-executing CLI, UTF-8/LF, exact two-file
scope, and diff checks passed.

No SSH, `--execute`, scratch access, alternate run ID, target access, Grok,
or background writer ran. E22 remains consumed and its runbook is historical.
The next separate candidate is to author a new conservative runbook and
evidence identity using the current protected hashes. That docs-only slice
must not execute the rehearsal; live execution remains a later explicitly
authorized gate.

## E24 replacement rehearsal runbook — 2026-08-11

This section preserves the pre-execution E24 contract; E24 is now consumed.
E24 defined a new non-target identity without altering or reusing consumed
E22 evidence. The
[archived E24 runbook](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e24-2026-08-11.md)
fixes run ID `api-duckdb-scratch-e24-20260811-01`, its exact path below the
existing scratch prefix, evidence directory
`.codex-grok-tasks/api-duckdb-scratch-rehearsal-e24-20260811-codex01/`, the
E23 implementation/test hashes, one invocation, one cleanup check, four
classifications, and fail-closed evidence requirements.

This docs-only slice ran no SSH, `--execute`, scratch query or mutation,
target access, Grok, or background writer. The remote exact root was not
queried; collision handling remains inside the harness and consumes E24
without fallback. A latest explicit authorization for the isolated E24 run is
still required before the documented command may execute.

### Consumed E24 outcome

The later authorized invocation exited `0` with valid strict JSON and five
`PASS` plus two `BLOCKED` results. Timing, scratch pause/resume, watchdog,
same-directory rename, and file/directory sync passed. Descriptor visibility
and metadata capability both stopped at the same compatibility boundary:
remote `Path.write_text` rejected its `newline` keyword before either probe's
intended operation. No remote interpreter-version claim is inferred.

The one cleanup check exited `0`, proving exact E24 root
`/tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e24-20260811-01`
absent. No retry, fallback identity, manual cleanup, target action, or Grok
run occurred. E24 is consumed; both branches remain ineligible and status remains
`CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`.

The next separate candidate is a local TDD compatibility fix for both
embedded text writes. It must use an explicit LF file-open path accepted by
the remote API and must not execute SSH. A later live attempt requires a new
runbook, identity, and explicit authorization.

## E25 remote text compatibility correction — 2026-08-11

E25 replaces the two incompatible
`Path.write_text(..., newline="\n")` calls with explicit
`Path.open("w", encoding="ascii", newline="\n")` contexts and ordinary
`write` calls. Probe order, target boundaries, result schema, cleanup, SSH
transport, and single-attempt behavior are unchanged.

The behavioral regression test extracts only the descriptor and metadata
functions plus their imports from the embedded AST. It installs a legacy
`Path.write_text` signature and deterministic fake `lsof`, proving both
functions reach their intended logic without the E24 `TypeError` and without
SSH. A fresh-basetemp RED produced `2 failed`; targeted GREEN produced
`2 passed`; the final focused suite passed `35/35`. Ruff lint/format, outer
and embedded compile, compatibility token scan, default non-executing CLI,
UTF-8/LF, exact scope, and diff checks passed.

The first local RED command encountered a stale default pytest basetemp, and
the first GREEN exposed Windows open-file unlink behavior in the test harness.
Both were test-environment diagnostics; the final fake-`lsof` path models the
remote POSIX behavior without weakening the product assertion.

No SSH, `--execute`, scratch action, new run ID, target access, Grok, or
background writer ran during E25. The separate E26 section below records the
then-fresh conservative identity and protected hashes. This is historical
pre-execution truth; ledger E26 above records the later consumed outcome.

## E26 fresh rehearsal runbook — 2026-08-11

The
[archived E26 runbook](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e26-2026-08-11.md)
preserves the contract that reserved
run ID `api-duckdb-scratch-e26-20260811-01`, exact root
`/tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e26-20260811-01`,
and local evidence directory
`.codex-grok-tasks/api-duckdb-scratch-rehearsal-e26-20260811-codex01/`.
It protects implementation commit
`82a00622aa6f21b7c87a72edeafc979d1d213093` and the E25 script/test hashes.

The runbook permits at most one later invocation and one exact-path cleanup
check, only after a fresh user message explicitly authorizes E26. At authoring
time the run ID was unused in the tracked workspace, the local evidence
directory was absent, and the remote root was not queried. This docs-only
slice ran no SSH, `--execute`, scratch action, target access, Grok, delegation,
or background writer.

E26 readiness adds no live evidence. Both branches remain ineligible, runtime
status remains `CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`, and
production remains `candidate`. A collision or failed invocation consumes E26
without a fallback identity; seven non-target `PASS` values would still not
authorize target capture or improve production readiness.

### Consumed E26 outcome

The later authorized invocation exited `0` with valid strict JSON and six
`PASS` plus one `BLOCKED` result. Timing, scratch pause/resume, watchdog,
descriptor visibility, same-directory rename, and file/directory sync passed.
Descriptor visibility proved only the exact non-target scratch path through
`lsof`; cross-namespace target coverage remains unproved.

Metadata tool/ACL/xattr capability was `BLOCKED`. Mode round-trip passed, but
ACL tools were absent and remote Python exposed no `os.setxattr`, so neither
ACL nor xattr round-trip was proved. This is an observed capability gap, not
the E24 text-write compatibility failure and not evidence about target bytes.

The one cleanup check exited `0`, proving exact E26 root
`/tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e26-20260811-01`
absent. No retry, fallback identity, manual cleanup, target action, or Grok
run occurred. E26 is consumed; both branches remain ineligible and status
remains `CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`.

The next separate candidate is a local design/capability slice that resolves
the C05 metadata-preservation gap and proves a fail-closed ACL/xattr method
compatible with observed host capabilities. It must not create E27 or access
the target Pod/volume or DuckDB/WAL bytes.

## C05 metadata classification correction — 2026-08-11

This local TDD correction fixes only the embedded metadata status aggregation
after the consumed E26 non-target rehearsal. It does **not** rewrite E26.

**E26 remains immutable historical evidence.** Its recorded outcome stays
`SCRATCH_REHEARSAL_BLOCKED` and consumed. No E26 JSON, classification,
runbook, timestamp, or hash is altered by this slice.

**Local aggregation bug.** The embedded `check_metadata` probe already
recorded per-signal evidence (`mode_roundtrip`, `xattr_roundtrip`,
`acl_roundtrip`), and the design already allowed metadata to be `PARTIAL`
when only a subset of mode/xattr/ACL behavior is available. The aggregation
branch, however, promoted to `PARTIAL` only when xattr or ACL succeeded, so
mode-only success (exactly the E26 evidence shape: mode true, xattr false,
ACL false) was misclassified as `BLOCKED`. That ignored successful mode-only
evidence.

**Corrected future aggregation.** Future non-target runs of the same probe
classify as:

- `PASS` when mode, xattr, and ACL all round-trip;
- `PARTIAL` when any non-empty subset succeeds, including mode-only;
- `BLOCKED` only when all three signals fail.

This is a classification correction only. It does not invent ACL/xattr values,
relax C05, or reclassify the historical E26 pack.

**Ownership boundary that remains closed.** Host `/tmp` scratch (E26's
execution surface) does **not** satisfy Linux Kind-node C05/I06. E20 already
observed GNU tar 1.34 with `--xattrs`/`--acls` inside the Kind node while
`getfacl` and `getfattr` were absent. GNU tar primary documentation states
that `--compare` covers size, mode, owner, modification date, and contents; it
does not claim ACL/xattr value comparison. Double-verbose `--xattrs` listing
reports attribute names and lengths, not values. Tar flags, listing, or
compare alone therefore do **not** prove C05's non-secret ACL/xattr digest
contract.

**Runtime and production status unchanged.** Both branches remain ineligible.
Authoritative status remains `CAPABILITY_REHEARSAL_REQUIRED` /
`PRESERVATION_PARTIAL`. Production remains `candidate`. No capture operator
runbook is approved.

**Next separate candidate.** A later local design/implementation may define a
node-scoped non-secret metadata inspector or an explicitly authorized
read-only node capability check that can prove ACL/xattr value digests under
C05 without target mutation. No E27 rehearsal identity is reserved here.

## C05 local POSIX metadata inspector — 2026-08-11

Local-only TDD slice. Product surface:
`scripts/inspect_posix_metadata.py` with focused unit tests in
`tests/unit/test_inspect_posix_metadata.py`. Standard-library reader only;
no SSH, Docker, kubectl, tar, subprocess, or database libraries; never opens
or hashes regular-file contents.

**Fail-closed contract.** Requires a POSIX-absolute `--root` (leading `/`;
Windows drive/UNC spellings rejected), pinned `--expected-device` /
`--expected-inode`, and positive `--max-entries`. CLI parse/validation
failures (missing required flags, invalid integers) emit the same bounded
`METADATA_INSPECTION_BLOCKED` JSON/exit contract rather than raw argparse
text; `--help` remains exit 0. Succeeds only when effective UID is zero, the
root is a real directory (not a symlink), and root `lstat` device/inode match
the caller pins. Traversal uses `lstat` / `follow_symlinks=False` only; never
resolves or walks through symlinks; never crosses the root device; admits only
directory, regular file, and symlink objects. Relative paths preserve literal
backslash characters in filenames (no `\\`→`/` rewrite). Enforces
`max_entries` (including root). Detects point-in-time drift on per-entry
identity metadata, xattr name sets, each directory's identity after its
subtree is walked, and whole-root stability after traversal. Any
validation/inspection failure returns no successful partial inventory
(`METADATA_INSPECTION_BLOCKED`, empty records, nonzero CLI exit). Success
emits one strict JSON object with `METADATA_INSPECTION_PASS`, schema version,
root identity, effective UID, deterministic records, and a claim boundary
stating metadata-only / no C05 / branch / capture / production approval.

**Non-secret xattr/ACL digest.** Uses `os.listxattr` and `os.getxattr` with
`follow_symlinks=False`. Sorts attribute names by encoded bytes and hashes a
length-prefixed name/value stream (SHA-256). Emits only xattr count, combined
digest, and booleans for `system.posix_acl_access` /
`system.posix_acl_default` presence. Raw xattr names and values never leave
the process. Missing xattr APIs or read errors fail closed.

**Live evidence status.** This inspector is implemented and unit-tested
locally only. It has **not** been executed on the Linux Kind node and
therefore adds **no** live evidence identity. E26 remains consumed and
immutable. GNU tar alone still does not prove xattr/ACL value digests (see
classification correction above). Runtime and production status are unchanged:
both branches remain ineligible; authoritative status remains
`CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`; production remains
`candidate`. This slice does not relax C05 and does not call the tool, branch,
or runtime ready.

**Independent review.** One local QA/fix follow-up corrected strict blocked
JSON for CLI parse failures, POSIX-only root/path handling, literal backslash
filename preservation, and nested-directory drift detection. The final
focused suite passes 14 tests. The later separately authorized read-only
non-target/node capability invocation is recorded below. No target
database-byte access or E27 rehearsal was authorized by that local slice.

## C05 Kind-node metadata capability gate — 2026-08-11

Authorized one-shot non-target node-only gate. Evidence identity:
`.codex-grok-tasks/c05-node-metadata-capability-20260811-grok01/`. Control
runner:
`.grok-prompts/c05-node-metadata-capability-runner-20260811-grok01.py`.
Transport: local OpenSSH to `deproject-mac`, Docker context
`colima-agentflow-fc5-7113966`, Kind node
`agentflow-reverify-ed03fc47-control-plane`, exact non-target root `/usr/bin`.
Inspector stdin-only; no remote file create/write/delete.

**Observed result.** Classification
`C05_NODE_METADATA_API_PASS_VALUE_DIGEST_UNEXERCISED`. Inspector status
`METADATA_INSPECTION_PASS` (exit 0). Entry count `376`. Total xattr count
represented by digests `0` (APIs available; no observed entry had an xattr
value, so value digests were unexercised). Inspector invocations `1`; raw
retries `0`. Result SHA-256
`92874862c6d9d2883729e8603b92fda0454730edbe9eecdb2bcca294b7910fd7`.
Protected inspector SHA-256 remains
`3a9a7e0714be3a8db5b70eb72273899611932e6b432e3e9067fc1d58ccba4dc9`.

**Claim boundary.** This is non-target node-only evidence. It does **not**
approve C05, a capture branch, recovery, or production. It does **not** access
target Pod/volume, `/data`, kubelet Pod-volume paths, or DuckDB/WAL bytes, and
does not open or hash regular-file contents. E26 remains consumed and
immutable. Both runtime branches remain ineligible; authoritative status
remains `CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`; production
remains `candidate`.

### Next-session transparent resume

Repository entry for this transparency update is
`a5f6951bb10c67b2966a215a85fa2f70b7f82391`; `main` was ahead of
`origin/main` by 70 with a clean tracked tree and index. The scoped successor
contains this tracked clarification. The evidence pack remains intentionally
local and untracked under the identity above.

Evidence pack SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| `execution.json` | `657b0fe1d4f7cce38a9c0994582b896f3e10a38b1b0832c4ea6fa083e4983186` |
| `preflight.json` | `74eb6030fea6af54ed23f8725d0187d8655e85844040e874389a162fb992b68d` |
| `result.json` | `92874862c6d9d2883729e8603b92fda0454730edbe9eecdb2bcca294b7910fd7` |
| `result.md` | `2435abb07e99c476426688167cd4b62f1305aaa5610954a36e6a3b5ae410eb17` |
| `evidence.md` | `25497fec31e9cb53dcadbe7545709bb455054649892a3a7f6b38bc233ffb8f18` |

The owner authorization for this one-shot slice is fully consumed: the
inspector ran once, raw retry count is zero, and no writer remains active.
A generic `continue` / `продолжи` message does **not** authorize another SSH,
Docker exec, discovery probe, or inspector run.

The remaining gap is precise: `listxattr` and `getxattr` exist in the Kind
node, but all 376 `/usr/bin` records had `xattr_count=0`, so no real xattr
value passed through the length-prefixed digest path. A distinct future gate
may close only this gap by using bounded metadata-only discovery to select an
existing non-target path with at least one xattr, then invoking the inspector
once under a new evidence identity. It requires fresh explicit owner
authorization, must not reuse `/usr/bin` or this identity, and must stop
without fallback if no safe value-bearing non-target path is found. Target
Pod/volume, kubelet Pod-volume paths, `/data`, DuckDB/WAL bytes, E27, remote
mutation, restart/recovery, production action, and push remain prohibited.

## C05 node xattr discovery terminal result — 2026-08-11

Authorized one-shot bounded metadata-only discovery of an existing
xattr-bearing non-target path. Evidence identity:
`.codex-grok-tasks/c05-node-xattr-discovery-20260811-grok01/`.
Route/model: `local_grok_cli`; requested `grok-4.5`, actual
`grok-4.5-build`. Remote controller executed exactly once before this
docs-only closure. Entry HEAD
`b451458bb26bd9781812873d50bd6fd78b7b8e5a`.

**Observed result.** Classification
`C05_NODE_XATTR_DISCOVERY_NO_SAFE_VALUE_PATH`. Discovery status
`NO_SAFE_XATTR_PATH` (exit `0`). Entries examined: `5205` across all 8
allowlisted roots. Selected path: `null`. Inspector invocations: `0`;
raw retries: `0`; total xattrs: `0`. Runner exit: `0`; strict JSON: true.

Evidence pack SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| `execution.json` | `7c21bc31141a1faea7ac748696d6dde7b5c1dc0208199c32aa166e341d6dd53f` |
| `discovery.json` | `12f246f246ae6a0b324313439a22561d56e92830895e22b97f70fa4b16041560` |
| `result.json` | `1ae8c53deaf76e1a517f2dcca7753a12baf72243ae83e76077a08d4889cee605` |
| `result.md` | `72cffc49abf461646ad81afcbd13b12de1fb3b0b3130cb941ac556d5d6be621c` |
| `evidence.md` | `d93562319003aa941562a4a0f8e1393e31c77953258c587489157df9e8ee4336` |

Protected SHA-256 unchanged:

- `scripts/inspect_posix_metadata.py`:
  `3a9a7e0714be3a8db5b70eb72273899611932e6b432e3e9067fc1d58ccba4dc9`
- `tests/unit/test_inspect_posix_metadata.py`:
  `bac58980103049c2af2586345b0e6b7f4f17f73f0996d1fb828724290cd6a72c`

**Claim boundary.** This is non-target discovery-only terminal evidence for
the authorized gate. It does **not** approve C05, a capture branch,
recovery, or production. No regular-file contents, target path, `/data`,
kubelet Pod-volume path, or DuckDB/WAL bytes were accessed. No remote write,
mutation, E27, restart, recovery, traffic, production action, commit, or
push occurred. Inspector was not invoked because no safe value-bearing path
was selected. E26 remains consumed and immutable. Both runtime branches
remain ineligible; authoritative status remains
`CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`; production remains
`candidate`.

The owner authorization and evidence identity are fully consumed. A generic
`continue` / `продолжи` does **not** authorize another remote command. Do
not treat a fallback discovery or another inspector invocation as automatic
next work; any later distinct gate requires fresh explicit owner
authorization.

## C05 node xattr additional-roots discovery terminal result — 2026-08-11

Authorized second one-shot bounded metadata-only discovery over the exact
additional allowlisted non-target roots. Evidence identity:
`.codex-grok-tasks/c05-node-xattr-additional-discovery-20260811-grok01/`.
Route/model: `local_grok_cli`; requested `grok-4.5`, actual
`grok-4.5-build`. Remote controller executed exactly once before this
docs-only closure. Entry HEAD
`3253ad780fbc90dfdfe7b4acf87c9aaf525287fd`.

Exact additional allowlist:
`/usr/share`, `/usr/include`, `/usr/libexec`, `/var/lib/apt`,
`/var/lib/systemd`, `/var/cache/debconf`, `/var/spool`, `/srv`.

**Observed result.** Classification
`C05_NODE_XATTR_DISCOVERY_NO_SAFE_VALUE_PATH`. Discovery status
`NO_SAFE_XATTR_PATH` (exit `0`). Entries examined: `2007` across all 8
additional allowlisted roots. Selected path: `null`. Inspector invocations:
`0`; raw retries: `0`; total xattrs: `0`. Controller exit: `0`; strict
JSON: true; result status `METADATA_INSPECTION_NOT_RUN`.

Evidence pack SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| `execution.json` | `df792962a138cdc778fb0b07c69afa573fb6f8b4e20911a421b362b6af3eaf0b` |
| `discovery.json` | `9319dff407cf222fde3324592bf5953defa00c430e3139f7e730eb92d7c2573b` |
| `result.json` | `71a012663fe62251367b4f04080824892327d53c1ef796368b3796e657afaf21` |
| `result.md` | `256b989a1b4c6f7e685d38f385ce16b39f838ace817a5649f169657fe92277ab` |
| `evidence.md` | `ea67f4764b3196a2423aa9f4afc5899aed4d0c643247b4b0aac2ae7b7ff7aced` |

Protected SHA-256 unchanged:

- Base controller:
  `2601f65eb3270d3827927ad4c8122545149391597cf2d16179b61a43d221047d`
- Additional controller:
  `cfe6d72a52fc936e7bffb4b1f0234e7beb38e9678d3c6ccdd1ed0210e39eb00f`
- Inspector (`scripts/inspect_posix_metadata.py`):
  `3a9a7e0714be3a8db5b70eb72273899611932e6b432e3e9067fc1d58ccba4dc9`
- Focused test (`tests/unit/test_inspect_posix_metadata.py`):
  `bac58980103049c2af2586345b0e6b7f4f17f73f0996d1fb828724290cd6a72c`

**Claim boundary.** This is non-target discovery-only terminal evidence for
the authorized additional-roots gate. It does **not** approve C05, a capture
branch, recovery, or production. No regular-file contents, target path,
`/data`, kubelet Pod-volume path, or DuckDB/WAL bytes were accessed. No
remote write, mutation, E27, restart, recovery, traffic, production action,
commit, or push occurred. Inspector was not invoked because no safe
value-bearing path was selected. E26 remains consumed and immutable. Both
runtime branches remain ineligible; authoritative status remains
`CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`; production remains
`candidate`.

The owner authorization and evidence identity are fully consumed. A generic
`continue` / `продолжи` does **not** authorize another remote command. Do
not treat a fallback discovery or another inspector invocation as automatic
next work; any later distinct gate requires fresh explicit owner
authorization.

## C05 synthetic non-target xattr value gate — 2026-08-11

Authorized one-shot reversible mutation in the exact Kind-node scratch path
`/tmp/c05-node-xattr-synthetic-20260811-codex02`. Evidence identity:
`.codex-grok-tasks/c05-node-xattr-synthetic-20260811-codex02/`. Executor:
Codex on Mac through Docker SDK 7.1.0 and Colima socket
`~/.colima/agentflow-fc5-7113966/docker.sock`; Docker Engine 29.2.1. Entry
HEAD `dceea5a61a12a42859f8b0ec033e4a7729c4b69e`; node
`agentflow-reverify-ed03fc47-control-plane`, pinned container ID
`0545702c4bc4ffdb5402b324af5dd51af71bed57ca7078707c931eae8aee365b`.
Grok was unavailable on Mac and did not run.

**Observed result.** Classification
`C05_SYNTHETIC_XATTR_VALUE_DIGEST_PASS`. The controller created one isolated
scratch directory and one test file, wrote xattr `user.c05_probe`, and invoked
the protected inspector exactly once. Inspector status
`METADATA_INSPECTION_PASS`; entry count `2`; the test file had
`xattr_count=1`. Observed and independently computed length-prefixed xattr
digests matched:
`78ee82b3c9a3d3b73b0342ca4da637b96ccdd2e6ea5529def7a34967dea70c7c`.
Mutation invocations `1`, inspector invocations `1`, cleanup invocations `1`,
runtime retries `0`. Exact cleanup passed and an independent post-state probe
confirmed the scratch path absent.

Evidence pack SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| `preflight.json` | `f35f32ebef61cab9ced4fc629b34a2256d0f759b7c2f62712ae707fc64ee90c3` |
| `execution.json` | `f29925a8b96d364fb58e969d234949ec385dc64e460665c640ca922c54f0bad2` |
| `inspector.json` | `e64cae7052bf3820894e4a102df9ad8db82d3fc9c09b743a674049df34729647` |
| `result.json` | `83362b030d6d22c0c9b690d7f21bfa08ac6838b7ba97badde49760ed17c413ee` |
| `result.md` | `1d5b052591160003ae15add07fc42fdff82d44510c32a015b2f41f7affd65f1c` |
| `evidence.md` | `9171a1cffe37d279afa2e61f7c4330dcf8ef855779cb4da45e1514556be6a082` |

Protected SHA-256 values remained unchanged:

- `scripts/inspect_posix_metadata.py`:
  `3a9a7e0714be3a8db5b70eb72273899611932e6b432e3e9067fc1d58ccba4dc9`
- `tests/unit/test_inspect_posix_metadata.py`:
  `bac58980103049c2af2586345b0e6b7f4f17f73f0996d1fb828724290cd6a72c`

**Claim boundary.** This closes only the previously unexercised real-value
digest path for the node Python xattr APIs and protected inspector. The source
was a synthetic non-target scratch file. It does **not** prove ACL or xattr
capture/restore preservation, target-volume feasibility, C05 approval, branch
eligibility, capture, recovery, or production readiness. No target Pod/volume,
`/data`, kubelet Pod-volume path, DuckDB/WAL byte, workload/dependency restart,
traffic, production action, or push occurred. The authorization and evidence
identity are consumed; no automatic successor gate is created.

## Upstream root-cause classification and local repro attempts — 2026-08-23

Local/read-only documentation slice on the Windows workstation. No SSH, no
target access, no runtime mutation, no push of live state. Executor: Claude
(session-delegated decisions, owner instruction 2026-08-23).

### Version identity (Repository contract)

`uv.lock` pins `duckdb == 1.5.4` both at the current HEAD and at the failing
image commit `ed03fc47` (`agentflow/api:ed03fc47-iceberg-live-20260801-01`).
The WAL was therefore written and replayed by the same DuckDB version — the
failure is **not** a version-skew replay.

### Upstream match (Observed, external)

The exact assertion string matches open upstream reports:

- [duckdb/duckdb#19712](https://github.com/duckdb/duckdb/issues/19712) —
  same error on WAL replay after a process crash; state `open`, label
  `needs reproducible example` (checked 2026-08-23).
- [duckdb/duckdb#20543](https://github.com/duckdb/duckdb/issues/20543) —
  same assertion, has a reproducer; `open`.
- [duckdb/duckdb#18259](https://github.com/duckdb/duckdb/issues/18259) —
  same replay failure for `ADD COLUMN ... DEFAULT <expr>` WAL records;
  `open`.

A 2026-05-27 forensic comment on #19712 reports ~80 % reproduction on
Windows with DuckDB v1.5.3 from **plain bulk DML followed by brutal process
termination** — no `ATTACH` involved — and three recovery properties
observed there: deleting the `.wal` alone did **not** restore read-write
open; `access_mode=READ_ONLY` opened successfully by skipping WAL replay
and allowed `EXPORT DATABASE`; export + import into a fresh database
recovered the data fully.

This upstream trigger class is consistent with the E6 abrupt-Colima-restart
**Inference**; it does not prove the origin for our bytes.

### Local reproduction attempts (non-target scratch, duckdb 1.5.4)

- 10 × brutal-exit cycles (`CREATE TABLE` with a default-expression
  column, 100 DML statements, `os._exit(0)` with no close/checkpoint,
  reopen): 10/10 clean replays.
- Torn-tail sweep: one 16,021-byte WAL truncated at 164 offsets, each
  reopened against a pristine base file: 161 clean opens, 3 parse-level
  failures at sub-header offsets, **0** internal errors, **0**
  `GetDefaultDatabase` failures.

Conclusion: a fully flushed or cleanly torn WAL replays correctly on
1.5.4; the failure requires a rarer interleaving (upstream evidence points
at termination while a checkpoint or multi-frame write is in flight).
This matches the upstream `needs reproducible example` status.

### Implications for the recovery options

1. The root cause is an **upstream DuckDB storage bug class**, not
   application misuse; no application code change can retroactively repair
   the failing file.
2. A DuckDB version bump cannot be claimed as remediation while the
   upstream issues remain open.
3. The upstream-validated `READ_ONLY` open + `EXPORT DATABASE` path is the
   preferred **capture** branch for a future owner-authorized runtime
   slice: it needs read access only and performs no WAL replay. It must be
   rehearsed against a copy first; it is not hereby authorized.
4. Prevention hardening candidates (separate change-controlled work, not
   this slice): a periodic `CHECKPOINT` to bound the WAL window, and a
   startup error path that names this design doc instead of a bare
   crash-loop exit.

### Second organic occurrence and live re-diagnosis — 2026-08-23

A later read-only pass the same day found that the 08-10 pod (`-kk8tf`)
and its emptyDir no longer exist: the ReplicaSet replaced the pod on
2026-08-18T18:49:45Z (new pod `-t2784`, UID
`da0b8feb-00cb-48f4-9833-fb529b17007d`). The new pod created fresh DuckDB
files at the same env paths and hit the **same** WAL-replay assertion
after a brutal stop (last WAL write Aug 19 16:48; 967 restarts by
2026-08-23). The `_fresh_20260807` basenames come from `DUCKDB_PATH`, not
from the data's age. Both 12,288-byte main files are byte-identical
pristine empty databases — no checkpoint ever ran; the whole record
history (~8.6 KB) sits in the two WALs. In-place SHA-256 values and the
operator recovery commands (capture via `docker cp` from the kind node,
then pod delete for a fresh emptyDir) are recorded in
`api-flink-recovery-runbook-20260823-01.md`. The forensic file set named
by the earlier sections of this design is gone with the old pod; the
current file set replaces it as forensic material. Two independent
occurrences on one stand strengthen the upstream classification above.

### Claim boundary for this classification slice

No target Pod/volume, `/data` path, DuckDB/WAL byte, pod `exec`, restart,
traffic, capture, recovery, production transition, or consumed-gate re-run
occurred (in-place `sha256sum` inside the kind node container is the one
read-only observation added on 2026-08-23). All prior gate outcomes and
consumed authorizations are unchanged.

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
4. **Live volume source and env are resolved by E17:** `/data` is the
   current Pod's 256Mi `emptyDir`; both fresh DuckDB paths are live.
5. **Live store selection is partially resolved by E17:**
   `SERVING_BACKEND=clickhouse` is explicit; `AGENTFLOW_CONTROLPLANE_STORE`
   is absent, so `embedded` is still the application-default inference.
6. **Whether future durability (PVC + backup wiring + single-writer
   enforcement already in chart) is required before any further soak** —
   separate program, not this design’s execution.
7. **Root-cause forensics** (why WAL unreplayable) only after a sealed master
   and disposable working clones exist; Colima restart remains Inference
   until then.
8. **Quiesce-and-copy runtime eligibility remains fail-closed after E26.** E26
   remains an immutable six-`PASS`, one-`BLOCKED` non-target result. The later
   synthetic Kind-node gate proves `setxattr`/`getxattr` and the inspector's
   value-digest path only for a newly created scratch file. It does not prove
   ACL/xattr capture-and-restore preservation or target-volume feasibility.
   Status remains `CAPABILITY_REHEARSAL_REQUIRED`; no capture operator runbook
   is approved.

### Session-delegated dispositions — 2026-08-23

Recorded under the owner's 2026-08-23 delegation ("continue autonomously,
decisions delegated"). These are **decision records only**; they authorize
no runtime action by themselves, and the owner may override them before any
future runtime slice.

1. **RPO (question 1):** total loss of the embedded control-plane state of
   this candidate stand is acceptable. The stand is a checkpoint-restore
   rehearsal deployment; its embedded records are synthetic rehearsal
   traffic; serving data lives in ClickHouse; production remains
   `candidate`.
2. **Discardable classes (question 2):** all embedded record classes are
   discardable **after** one best-effort read-only capture attempt
   (`READ_ONLY` open + `EXPORT DATABASE`, per the 2026-08-23
   classification above) has been made and its outcome recorded — whether
   it succeeds or fails.
3. **External backup (question 3):** none is known; treat as nonexistent.
4. **Recommended recovery branch:** read-only export capture, then fresh
   store files (new `DUCKDB_PATH`/usage-path basenames), leaving the
   failing file set in place untouched as forensic material. Execution
   requires its own explicitly authorized runtime slice under the
   fail-closed protocol of this design.

## Claim boundary for this documentation slice

| Claim | Status |
| --- | --- |
| Design document created | Yes (this file) |
| Ownership/lifetime/recovery contract established from repository + preserved evidence | Yes |
| Live metadata / preservation-feasibility gate executed | **Yes, read-only** (`METADATA_PASS`; `PRESERVATION_PARTIAL`) |
| E19 corrective design findings mapped | **Yes, 10/10** (`F01`–`F10`) |
| Live quiesce capability gate executed | **Yes, read-only** (`CAPABILITY_REHEARSAL_REQUIRED`; neither branch eligible) |
| Non-target rehearsal harness setup | **Yes, local only** (`REHEARSAL_SETUP_READY_NOT_EXECUTED`; seven checks `NOT_RUN`) |
| Seven non-target scratch probes implemented | **Yes**; the first live identity was transport-blocked before probe execution |
| Exact E22 cleanup proved | **Yes**; one read-only exact-path check exited `0` |
| Windows LF transport corrected | **Yes, local TDD only**; no new SSH or scratch action |
| Replacement E24 rehearsal | **Blocked**; five `PASS`, two `BLOCKED`, cleanup proved |
| E25 remote text compatibility | **Fixed and tested locally**; no new SSH or scratch action |
| E26 replacement rehearsal | **Blocked**; six `PASS`, metadata capability `BLOCKED`, cleanup proved |
| Live preservation, cleanup, restore, or API recovery executed | **No** |
| Quiesce-and-capture runbook approved | **No** (`CAPABILITY_REHEARSAL_REQUIRED`) |
| Production readiness improved | **No** |
| External dependency recovery re-run | **No** (must remain consumed) |
| Local C05 POSIX metadata inspector (API+CLI+unit tests) | **Yes, local only**; unit-tested; live non-target node gate recorded below |
| C05 Kind-node metadata capability (non-target `/usr/bin`) | **Executed once**; `C05_NODE_METADATA_API_PASS_VALUE_DIGEST_UNEXERCISED`; 376 entries; 0 xattrs; non-target only |
| C05 node xattr discovery (allowlisted non-target roots) | **Executed once**; `C05_NODE_XATTR_DISCOVERY_NO_SAFE_VALUE_PATH`; discovery `NO_SAFE_XATTR_PATH`; 5205 entries / 8 roots; selected path `null`; inspector invocations `0` |
| C05 node xattr additional-roots discovery | **Executed once**; `C05_NODE_XATTR_DISCOVERY_NO_SAFE_VALUE_PATH`; discovery `NO_SAFE_XATTR_PATH`; 2007 entries / 8 additional roots; selected path `null`; inspector invocations `0`; result status `METADATA_INSPECTION_NOT_RUN` |
| C05 synthetic non-target xattr value gate | **Executed once; PASS**; one isolated scratch file, one real xattr value, inspector `METADATA_INSPECTION_PASS`, observed digest matched independent calculation, exact cleanup and independent absence check passed; no C05/branch/capture/production approval |
| Next possible action | No automatic next work from this pack. Owner authorization and evidence identity are consumed. Do not treat fallback discovery or inspector invocation as automatic next work; any later distinct gate requires fresh explicit owner authorization. No E27, target DB-byte access, or C05/branch/capture/production approval from this pack |

---

*End of design. E26 remains consumed. The C05 node metadata, both
xattr-discovery gates, and the synthetic xattr value gate are non-target
evidence only and do not approve C05, capture, recovery, or production. The
synthetic gate closes only the inspector value-digest execution gap and passed
exact cleanup. No target or database-byte access was authorized or performed.*
