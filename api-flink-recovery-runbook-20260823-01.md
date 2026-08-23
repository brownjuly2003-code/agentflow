# API + stream-processor recovery runbook (2026-08-23)

**Runbook ID:** `API_FLINK_RECOVERY_20260823_01`.
**Scope:** the two kind blockers of the corrected-rollback front, live-diagnosed
read-only on 2026-08-23. Every command below carries an explicit
`--context` / `--profile`; the global docker context on the iMac points at
another project (`colima-nsa`) and must not be switched.
**Execution status:** NOT executed. The diagnosing session's tooling blocks
byte-copy and mutating commands on the remote stand; the operator runs the
steps below (or a later session with those permissions granted).

## Blocker 1 — API pod CrashLoopBackOff (DuckDB WAL replay)

### Live diagnosis (read-only, 2026-08-23 ~13:30Z)

- Pod `agentflow-chk-restore-rv-api-20260802-01-59489dd45c-t2784`,
  UID `da0b8feb-00cb-48f4-9833-fb529b17007d`, created
  `2026-08-18T18:49:45Z`, **967 restarts**. Current log shows the same
  assertion as the 08-10 design-doc capture:
  `Failure while replaying WAL file "/data/agentflow_fresh_20260807.duckdb.wal":
  Calling DatabaseManager::GetDefaultDatabase with no default database set`.
- This is a **second organic occurrence**: the 08-10 pod (`-kk8tf`) and its
  emptyDir are gone; the current pod created fresh files on 08-18 (the
  `_fresh_20260807` basenames come from env `DUCKDB_PATH`, not from the data's
  age) and hit the same upstream bug class
  (duckdb #19712/#20543/#18259) after a brutal stop.
- `/data` volume contents (node path
  `/var/lib/kubelet/pods/da0b8feb-00cb-48f4-9833-fb529b17007d/volumes/kubernetes.io~empty-dir/data`):

| File | Bytes | mtime | SHA-256 |
| --- | --- | --- | --- |
| `agentflow_fresh_20260807.duckdb` | 12,288 | Aug 18 18:49 | `e507ee3e10ae6f57180779e68b3a94db0575566b063bb6d997fa83815507a5e6` |
| `agentflow_fresh_20260807.duckdb.wal` | 4,461 | Aug 19 16:48 | `ea6e0855a4b97e444165980ac28c6460aaf61f60afca80c95ab03fb8422442f8` |
| `agentflow_api_fresh_20260807.duckdb` | 12,288 | Aug 18 18:49 | `e507ee3e10ae6f57180779e68b3a94db0575566b063bb6d997fa83815507a5e6` |
| `agentflow_api_fresh_20260807.duckdb.wal` | 4,140 | Aug 18 22:14 | `0c302d1ac9c6f883c393daceef43289bbc8c54309ca440d07c335a42f3fe8563` |

  Both 12,288-byte main files are byte-identical pristine empty databases
  (identical hash): **no checkpoint ever ran**; the entire record history
  (~8.6 KB) sits in the two WALs. The last write is Aug 19 16:48 — the
  brutal-stop moment; the pod has crash-looped since.

### Recovery steps (per the recorded 2026-08-23 dispositions)

1. **Capture (before any mutation; emptyDir dies with the pod):**

   ```bash
   ssh julia@192.168.1.133
   export PATH=/usr/local/bin:$PATH
   mkdir -p ~/agentflow-api-data-capture-20260823-01
   docker --context colima-agentflow-fc5-7113966 cp \
     agentflow-reverify-ed03fc47-control-plane:/var/lib/kubelet/pods/da0b8feb-00cb-48f4-9833-fb529b17007d/volumes/kubernetes.io~empty-dir/data \
     ~/agentflow-api-data-capture-20260823-01/data
   shasum -a 256 ~/agentflow-api-data-capture-20260823-01/data/*
   ```

   Compare against the table above; identical hashes = capture is exact.
   (A best-effort `READ_ONLY` open + `EXPORT DATABASE` of the *copy* can be
   attempted afterwards at leisure; per the dispositions its outcome — either
   way — does not block step 2 once the copy exists.)

2. **Recreate the store (only after step 1 hashes match):**

   ```bash
   kubectl --context kind-agentflow-reverify-ed03fc47 -n agentflow \
     delete pod agentflow-chk-restore-rv-api-20260802-01-59489dd45c-t2784
   ```

   No spec change: the ReplicaSet creates a new pod with a fresh emptyDir;
   the API creates new DuckDB files at the same env paths and starts clean.

3. **Verify:**

   ```bash
   kubectl --context kind-agentflow-reverify-ed03fc47 -n agentflow get pods
   # expect the new api pod 1/1 Running, RESTARTS 0
   kubectl --context kind-agentflow-reverify-ed03fc47 -n agentflow \
     get endpoints agentflow-chk-restore-rv-api-20260802-01
   # expect a non-empty endpoint
   ```

**Abort:** if step 1 hashes do not match the table (files changed since
diagnosis), stop and re-diagnose — do not delete the pod.

## Blocker 2 — stream-processor CrashLoopBackOff (stale Flink HA pointer)

### Live diagnosis (read-only, 2026-08-23 ~13:35Z)

- Pod `agentflow-soak-rv-stream-processor-6c77bc9574-9x77q`, **849
  restarts**, deployment age 4d16h (the 20260818-06 golden-soak-rv
  identity). Fatal on every start:
  `Could not recover job with job id 80e6e2be68fde261e281b847f1a0ae44 ...
  FileNotFoundException: /tmp/agentflow-golden-soak-rv-20260818-06/checkpoints/ha/agentflow-soak-rv-stream-processor/submittedExecutionPlanb4778d6a85f2`
  — Flink's own message: "Try cleaning the state handle store."
- Mechanism: HA pointers live in the Kubernetes HA ConfigMap
  `agentflow-soak-rv-stream-processor-80e6e2be68fde261e281b847f1a0ae44-config-map`
  (age 3d20h), while the pointed-to blobs lived under container-local
  `/tmp/...` (no volume is mounted for it — verified in the pod spec) and
  were lost on container restart. The pointer survives, the blob does not →
  permanent recovery crash-loop. The stand's declared `upgradeMode` is
  stateless (root plan), so the lost checkpoint carries no restore
  obligation.

### Recovery step

```bash
kubectl --context kind-agentflow-reverify-ed03fc47 -n agentflow \
  delete configmap agentflow-soak-rv-stream-processor-80e6e2be68fde261e281b847f1a0ae44-config-map
kubectl --context kind-agentflow-reverify-ed03fc47 -n agentflow \
  delete pod agentflow-soak-rv-stream-processor-6c77bc9574-9x77q
```

The JobManager then starts with no stale job to recover and submits the
application job fresh (stateless submit). Verify: pod reaches 1/1 Running,
log shows the job switching to `RUNNING`, and no
`Could not recover job` line appears.

**Leave alone:** `...-cluster-config-map`, `flink-config-...`,
`pod-template-...`, `autoscaler-...` ConfigMaps — only the per-job
`...-80e6e2be...-config-map` holds the stale pointer.

## Claim boundary

Read-only diagnosis only: in-place hashes, pod/deployment specs, logs, and
ConfigMap listings. No byte was copied off the stand, no pod, ConfigMap,
volume, or file was mutated, no traffic ran, and the co-tenants
(ClickHouse, MinIO, Iceberg REST, kind node — all Up ~30 h and healthy)
were not touched. Production stays `candidate`. Executing this runbook
closes only the two CrashLoop blockers; the corrected-rollback rehearsal
itself remains a separate gate.
