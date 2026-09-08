# External-dependency recovery preparation — 2026-08-17

## Goal and current state

**Goal:** prepare one fail-closed, data-preserving live recovery of the existing
ClickHouse / MinIO / Iceberg REST Compose containers so Codex can request a
single exact remote-mutation authorization later.

**Current state (authoritative, not live):** handoff `RECOVERY_FOCUS_20260817_01`
in [AGENT_STATE.md](AGENT_STATE.md) / [docs/SESSION_HANDOFF.md](docs/SESSION_HANDOFF.md)
is sole next-session truth. Last **proved** 2026-08-17 evidence (stale for “now”;
re-observe before mutate): ClickHouse, MinIO, Iceberg REST stopped (`restart=no`,
Docker exit `255` / Moby restore); bridge + lake materializer CrashLoop on CH /
Iceberg refuse; API independently CrashLoop on DuckDB WAL. The 2026-08-10 PASS in
[docs/operations/external-dependency-recovery-gate.md](docs/operations/external-dependency-recovery-gate.md)
is **historical and stale** after the later Colima stop/start — not current
readiness and not standing authorization. No live remediation is authorized here.

Contracts:
[scripts/recover_external_dependencies.py](scripts/recover_external_dependencies.py),
[tests/unit/test_external_dependency_recovery.py](tests/unit/test_external_dependency_recovery.py),
[docs/operations/external-dependency-recovery-gate.md](docs/operations/external-dependency-recovery-gate.md);
API WAL separation
[docs/operations/api-duckdb-persistence-recovery-design.md](docs/operations/api-duckdb-persistence-recovery-design.md)
(Outcome; invariant 8); 2026-08-17 RCA
[colima-runtime-stabilization.md](colima-runtime-stabilization.md)
(“Latest authorized workload CrashLoop RCA”, “Follow-up external exit-255 forensics”).

## Pre-mutation checklist (read-only preflight must pass first)

| Check | Exact contract value |
| --- | --- |
| SSH host | `deproject-mac` |
| Colima profile / socket | `agentflow-fc5-7113966` → `unix:///Users/julia/.colima/agentflow-fc5-7113966/docker.sock` |
| Kind node | `agentflow-reverify-ed03fc47-control-plane` **running** |
| CH project / service / container | `agentflow-ch-rv-20260802-01` / `clickhouse` / `agentflow-ch-rv-20260802-01` |
| CH Compose file | `/tmp/agentflow-chk-restore-rv-20260802-01/clickhouse-compose.yml` |
| CH image | `clickhouse/clickhouse-server:24.8` |
| CH volume mount | named volume `agentflow-ch-rv-20260802-01-data` at `/var/lib/clickhouse` |
| Iceberg project | `agentflow-iceberg-rv-20260802-01` |
| Iceberg Compose file | `/tmp/agentflow-iceberg-ed03fc47-20260801-01/docker-compose.iceberg.yml` |
| Iceberg services (exact set) | `minio`, `minio-init`, `iceberg-rest` only |
| MinIO container / image | `{iceberg_project}-minio-1` / `minio/minio:RELEASE.2025-09-07T16-13-09Z` |
| minio-init | `{iceberg_project}-minio-init-1`, `minio/mc:RELEASE.2025-08-13T08-35-41Z`, prior successful one-shot (`exited`, exit `0`) |
| Iceberg REST | `{iceberg_project}-iceberg-rest-1` / `tabulario/iceberg-rest:0.6.0` |
| All four dependency containers | project/service/compose-file ownership, expected image, restart policy **`no`** |
| Safe preflight states | CH/MinIO/Iceberg REST: `exited` or `running` (if running, CH/MinIO healthy); never create a substitute MinIO |
| Persistence | CH named volume identity intact; MinIO data = **existing container writable layer** (missing/replaced MinIO = hard fail) |

Default mode only inspects; any owner/label/service/persistence mismatch exits
nonzero **before** start/stop.

## Command surface (future / authorized-only — not executed here)

Read-only preflight (remote SSH+Docker inspect; no start/stop):

```powershell
.venv\Scripts\python.exe scripts\recover_external_dependencies.py
```

**First remote mutation boundary** — only after fresh exact user authorization
and successful preflight. Mutation begins inside `recover_dependencies` on the
first `docker compose … start SERVICE` (never `up` / `down` / `rm` / volume delete):

```powershell
.venv\Scripts\python.exe scripts\recover_external_dependencies.py `
  --execute `
  --acknowledge-live-recovery COLIMA_RESTART_DEPENDENCY_LIFECYCLE_GAP
```

Token must match exactly `COLIMA_RESTART_DEPENDENCY_LIFECYCLE_GAP`. Do **not**
raw-retry after first success or first failure+rollback; no second attempt
without a new authorization.

## Data-preservation invariants

- **ClickHouse:** existing named volume `agentflow-ch-rv-20260802-01-data`; start
  existing container only; never recreate without that volume.
- **MinIO:** existing container writable layer; never create a replacement as
  data substitute.
- **Iceberg REST:** start existing container only; no recreate/remove.
- **minio-init:** one-shot; prior `exited (0)` at preflight; on recovery may
  re-run and must complete `exited (0)` before Iceberg REST start; not left as
  a long-running service after success.

## Start order, gates, fail-fast, rollback, stop rule

When a service is not already running:

1. Start ClickHouse → wait Docker **healthy**.
2. Start MinIO → wait Docker **healthy**.
3. If Iceberg REST was `exited`: start `minio-init` → wait **exited 0** (drop
   from rollback-started set after success).
4. Start Iceberg REST → wait container **running**.
5. Kind probes: CH `http://172.18.0.1:8123/ping` body `Ok.`; MinIO
   `http://172.18.0.1:9000/minio/health/live`; Iceberg REST
   `http://172.18.0.1:8181/v1/config` valid JSON object.
6. Iceberg probe: retry **only** `curl: (7)` every 2s within timeout; re-inspect
   after each refusal; **fail-fast** on terminal state or non-refusal error;
   timeout fails (no unbounded wait).

On post-start failure: **reverse-order** `compose stop` **only** services this
invocation started; leave pre-existing healthy services; no remove/volume-delete;
report original error plus rollback errors; never emit `status=ready` /
`ready_for_workload_verification=true` on failure. **No raw retry.**

## Artifacts for the future live slice

Fresh untracked evidence dir (e.g.
`.codex-grok-tasks/external-dependency-live-recovery-20260817-<id>/`; do not
reuse 2026-08-09/10 packs): stdout/stderr of the single authorized execute; JSON
(`status`, `ready_for_workload_verification`, `started_services`, `gates`,
`data_preservation`, `rollback`); service/container identity and state (name,
project/service, image, status/health/exit_code); rollback errors when present;
UTC window, entry HEAD, executor, exit code; SHA-256 of captures recorded by
Codex after write (not invented here).

## Acceptance criteria

**Dependencies (this slice):** exit `0`; JSON `status=ready` and
`ready_for_workload_verification=true`; gates
`clickhouse=healthy_and_kind_reachable`, `minio=healthy_and_kind_reachable`,
`minio_init=exited_0`, `iceberg_rest=running_and_kind_reachable`; CH volume +
MinIO writable-layer preservation; no create/recreate/delete.

**Subsequent observation only (separate decision):** read-only check whether
bridge and lake materializer become Ready / regain endpoints.
**Do not claim API recovery** from dependency recovery; API WAL is a separate chain.

## Explicit exclusions

API DuckDB/WAL mutation; clock / idle-I/O gates; traffic; soak; production
transition; source deployment / chart edits; secret reads; push; Colima
profile/config change; Kubernetes mutation; container create/recreate/remove;
volume delete; raw retry; initiating-stop forensics; merging API WAL with
dependency recovery.

## Authorization sentence (quote verbatim later)

Разрешаю один bounded live recovery внешних зависимостей командой
`python scripts/recover_external_dependencies.py --execute --acknowledge-live-recovery COLIMA_RESTART_DEPENDENCY_LIFECYCLE_GAP`
(только `compose start` существующих ClickHouse/MinIO/minio-init/Iceberg REST;
rollback — reverse `compose stop` только сервисов, стартованных этим запуском,
без remove/volume-delete); прогон останавливается после первого успеха или
первой ошибки с записью rollback — без raw-retry.

## Local verification checklist (Codex must run — not claimed passed)

Protected sources must remain byte-identical (baselines from task prompt; Codex verifies):

| Path | Baseline SHA-256 |
| --- | --- |
| `scripts/recover_external_dependencies.py` | `5CAAB93AD212CB61B2A91E6A4B8C02021523B8F509F4AE281ACE5439175A3AE1` |
| `tests/unit/test_external_dependency_recovery.py` | `4F63A230ED5F9B34F3F049EE273A588678DE8B2F92472C9CE1E7561613BCD210` |
| `docs/operations/external-dependency-recovery-gate.md` | `AD736D321DC70CCFEA4325BBBA8389D6FA98EBFBA07BE27CA3DFB87CC76B4F60` |
| `docs/operations/api-duckdb-persistence-recovery-design.md` | `EB2B4A8E56FD1CD864A6B833D5DDD3E8BD9A4821A2CB49B95E3C0780BD9F0371` |
| `colima-runtime-stabilization.md` | `14E3BA728EBD64E33322DE67A0CFE22244B920AC93834CDABA328E5C41E5607C` |

```powershell
git status --short --branch
git rev-parse HEAD
.venv\Scripts\python.exe -m pytest tests\unit\test_external_dependency_recovery.py -q
.venv\Scripts\python.exe -m ruff check scripts\recover_external_dependencies.py tests\unit\test_external_dependency_recovery.py
.venv\Scripts\python.exe -m ruff format --check scripts\recover_external_dependencies.py tests\unit\test_external_dependency_recovery.py
.venv\Scripts\python.exe -m py_compile scripts\recover_external_dependencies.py
git diff --check -- external-dependency-recovery-preparation-20260817.md
```

**Future/authorized-only:** remote preflight and `--execute` recovery; any
SSH/Mac/Docker/Kubernetes observation after authorization.

## Ambiguity remaining for exact authorization

Live container status/health/image IDs, Compose files under `/tmp`, volume
identity, and kind-node reachability must be re-observed by a fresh preflight
at authorization time — 2026-08-17 evidence is not a live guarantee. If
preflight fails, do not authorize execute; remediate ownership under a different
contract first.
