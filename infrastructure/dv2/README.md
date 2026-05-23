# DV2.0 Multi-Branch Demo — Infrastructure

Declarative Kubernetes manifests for the local kind-based demo cluster used by
the DV2.0 multi-branch extension. Mirrors the running `hq-demo` cluster on the
iMac demo host; rebuild from scratch with `bootstrap.sh`.

## Files

| File                       | Purpose                                                                 |
| -------------------------- | ----------------------------------------------------------------------- |
| `kind-hq-demo.yaml`        | Three-node kind cluster (control + 2 workers) with `branch`/`nodepool`/`workload` labels |
| `namespace.yaml`           | `dv2` namespace tagged `branch=msk tier=warm`                           |
| `secret.example.yaml`      | `ch-creds` Secret with demo creds (`default/demo`) — replace before prod |
| `clickhouse-sts.yaml`      | ClickHouse 25.5 StatefulSet pinned to `workload=clickhouse` worker, 5 Gi PVC, plus headless Service |
| `postgres-sts.yaml`        | Postgres 17-alpine StatefulSet pinned to `workload=postgres` worker, 2 Gi PVC, plus Service |
| `bootstrap.sh`             | One-shot rebuild: kind create → apply manifests → apply DV2.0 DDL → seed |

## Quick rebuild

```bash
# From any directory that can reach the Docker daemon
bash infrastructure/dv2/bootstrap.sh
```

`SEED=0 bash infrastructure/dv2/bootstrap.sh` skips the synthetic seed (DDL
only).

## Node placement legend

The kind config encodes the multi-branch storyline at the cluster level:

- `control-plane` node — `branch=msk nodepool=hq-control` (HQ control tier)
- worker 1 — `branch=msk nodepool=hq-data-tier-a workload=postgres` (hot OLTP)
- worker 2 — `branch=msk nodepool=hq-data-tier-b workload=clickhouse` (warm warehouse)

`nodeSelector` on each StatefulSet enforces that ClickHouse and Postgres land
on dedicated workers — the same primitive that production would use to keep
per-branch data on edge nodes (e.g. `branch=dxb` / `branch=ala`).

## Storage caveat

kind ships only the `local-path-storage` provisioner, so PVCs are hostPath
volumes inside Docker. **Re-creating the cluster destroys the data.** For
durable demo runs either:

1. Backup ClickHouse before teardown:
   ```bash
   kubectl exec -n dv2 clickhouse-0 -- clickhouse-client \
     --user default --password demo \
     --query "BACKUP DATABASE rv TO Disk('backups', 'rv.zip')"
   ```
2. Or skip teardown and `kubectl rollout restart` instead.

## ClickHouse SQL gotcha

Use `MD5(x)` directly — it already returns `FixedString(16)`. Do **not** wrap
it in `unhex(MD5(x))`; that double-encodes and produces a 32-byte string that
breaks `(hk, load_ts)` ORDER BY semantics across hubs and satellites.
