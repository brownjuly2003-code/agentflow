# E4 / S9 — live 2-pod topology proof (kind `hq-demo`)

Measured: `2026-07-09` on `deproject-mac` (Colima, kind cluster `hq-demo`).

## Goal

Prove the scale profile (`replicaCount=2`, `controlPlane.store=postgres`,
`serving.backend=clickhouse`) does **not** split-brain webhook registrations
across real pods — the sharpest class-5 failure mode from ADR 0010.

Automated checks: `scripts/k8s_replica_correctness_verify.sh` (Checks 1–2).
Delivery/alert recipes remain separate (store guarantees already in
`docs/perf/control-plane-pg-verify-2026-07-03.md`, 31/31).

## Topology

| Component | Placement |
|-----------|-----------|
| kind nodes | `hq-demo-control-plane`, `hq-demo-worker`, `hq-demo-worker2` (v1.32.2) |
| AgentFlow pods | **2** Ready, anti-affinity preferred → one on `worker`, one on `worker2` |
| Redis | 1 pod in `agentflow` |
| PostgreSQL control plane | `postgres-0` in `dv2` → DB `agentflow_cp` |
| ClickHouse serving | `clickhouse-0` in `dv2` |
| Image | `agentflow/api:staging` loaded into kind (`kind load docker-image`) |

Helm:

```bash
helm upgrade --install agentflow helm/agentflow \
  -f k8s/staging/values-staging.yaml \
  -f ~/values-hqdemo-scale.yaml \
  --namespace agentflow --wait --timeout 8m
```

## Results

### Check 1 — two ready pods on postgres store

```
PASS: 2 ready pods, all AGENTFLOW_CONTROLPLANE_STORE=postgres
```

| Pod | Node | Ready |
|-----|------|-------|
| `agentflow-…-8q9ll` | `hq-demo-worker` | 1/1 |
| `agentflow-…-kscc2` | `hq-demo-worker2` | 1/1 |

### Check 2 — Service-visible registration (script)

```
PASS: webhook visible on all 8 round-robin reads across pods
registered webhook_id=a24ccdd0-0b18-4eef-9286-bb13e5ddc3a4
```

Access path used: `kubectl port-forward svc/agentflow 18080:8000`
(NodePort socat to a fixed 30080 is brittle — this stand assigned **32456**).

### Cross-pod A→B (stronger probe)

Register on pod A, list on pod B (separate port-forwards):

```
reg on A → id=323a26ea-f1f2-4778-97b5-d5062005135d
list_A_has=yes
list_B_has=yes
CROSS_POD_OK: registration on A visible on B
```

This is the split-brain test the embedded YAML store would fail.

## Stand notes / fixes applied during the run

1. **Free RAM** — stop compose Flink/Kafka stack before starting kind (Colima 6 GiB).
2. **Image not on nodes** — `kind load docker-image agentflow/api:staging --name hq-demo`.
3. **Missing `psycopg`** — staging image lacked the optional `postgres` extra; install
   `psycopg[binary]` and re-commit the tag (scale profile requires it). Prefer baking
   `.[postgres]` into the staging Dockerfile for next builds.
4. **`mapfile`** — macOS bash 3.2 has no `mapfile`; script updated to a portable loop
   in `scripts/k8s_replica_correctness_verify.sh`.
5. **Kafka noise** — pods log rdkafka connect failures (no Kafka in this profile);
   readiness still green via `/v1/health`.

## Reproduce

```bash
export PATH=$HOME/bin:/usr/local/bin:$PATH
# kind nodes up; dv2 postgres+clickhouse Ready
bash ~/s6_e4_stage2_deploy.sh   # may need image load + psycopg first
kubectl -n agentflow port-forward svc/agentflow 18080:8000 &
BASE_URL=http://127.0.0.1:18080 bash scripts/k8s_replica_correctness_verify.sh
# optional: register on pod A, list on pod B via two port-forwards
```

## Status

**S9 / E4 automated topology proof: PASS** (Checks 1–2 + explicit A→B cross-pod).
