# E4 — two-real-pods replica-correctness topology proof (kind)

> Executed: `2026-07-11` on `deproject-mac` (kind + Docker on Colima vz, 6 GiB / 4 CPU,
> macOS 13.7.8 Intel). Code: `main` @ `9935bdc`.
> Closes the cutover-plan Phase 3 item that was **attempted-but-blocked on 2026-07-06**
> (shared-host resource crisis — kube control-plane crash-loop, build stall). This run
> freed the VM first and completed the proof.

## Result

`scripts/k8s_replica_correctness_verify.sh` → **exit 0, both checks PASS**:

- **[Check 1] ≥2 ready pods on the postgres store** — `deployment/agentflow` 2/2 Ready,
  every pod carries `AGENTFLOW_CONTROLPLANE_STORE=postgres`.
- **[Check 2] cross-pod registration visibility** — one webhook registered through the
  Service (`webhook_id=4a4709a0-0bdc-42bc-803a-2d49c1fb8f04`) was visible on **all 8
  round-robin reads across the two pods**. On the embedded per-pod store a read served by
  the pod that did not register would miss it (the sharpest split-brain, ADR 0010 class 5);
  on PostgreSQL the single registration table makes every read see it.

Checks 2–3 in the recipe (exactly-one delivery per (webhook,event); one alert page per
incident) need an event/alert emitter + capture sink and are not part of this automated
script. Their **store-level guarantee** (idempotent enqueue insert-win, single-flight
`claim_alert_tick`, outbox↔dead-letter atomicity) is already live-verified 31/31 by the
slice-5 standalone-PostgreSQL probe suite (`docs/perf/control-plane-pg-verify-2026-07-03.md`).
Phase 3 adds only the two-real-pods topology layer on top — done here.

## Topology stood up

- kind cluster `agentflow-staging` (`kindest/node:v1.31.0`), `k8s/kind-config.yaml`
  (NodePort 30080 → host 8080).
- Chart: `helm/agentflow` with `-f values-staging.yaml -f values-staging-scale.yaml.example`
  `--set serving.clickhouse.user=agentflow` →
  `replicaCount=2`, `persistence.enabled=false` (stateless request path),
  `serving.backend=clickhouse`, `controlPlane.store=postgres`.
- In-cluster deps (the chart ships neither PG nor CH): single-replica **PostgreSQL 16**
  (`agentflow-postgres`, control-plane store), **ClickHouse 24.8** (`agentflow-clickhouse`,
  serving backend), **Redis 7.4** (`agentflow-redis`, rate limit) + the two operator secrets
  `agentflow-controlplane-pg` (keyword-form DSN) and `agentflow-clickhouse`.
- Pods reach Ready without Kafka/Flink: `/v1/health` returns 200 with degraded components
  (each `HealthCollector` check is defensive), so readiness is process-up, not dependency-up.

## Environment gotchas found this run (Mac stand)

- The docker data disk (`/dev/vdb1`, ~59 G) is **separate from the VM root** (`/`, ~19 G):
  the first build died `[Errno 28] No space left on device` at the *pip install* step with
  the docker disk at 96 %, while `df /` still showed 18 G free. Freed it by removing the
  orphaned old DE-compose **named** volumes (`agentflow-docker-check_{clickhouse,kafka,minio}-data`,
  `…_flink-checkpoints`) — never `docker volume prune`/`system prune`, which would also
  delete co-tenant data (`rag_support_assistant_pgdata`, anonymous datalens/auto_bi volumes)
  and the stopped co-tenant containers themselves.
- The rendered Service takes an auto-assigned nodePort; patch it to **30080** so kind's
  fixed host mapping (`30080 → 127.0.0.1:8080`) reaches it, then `BASE_URL=http://127.0.0.1:8080`.
- Right after the nodePort patch, `curl` can time out for a few seconds until kube-proxy
  rewires the mapping — the verify script (run a moment later) succeeds.
- kind + a 2-replica agentflow + PG + CH + Redis fits in 6 GiB **only with the co-tenant
  containers stopped** (DataLens ×7 + auto_bi). The 2026-07-06 failure was exactly this
  contention; free the VM first (stop co-tenants, prune orphaned DE volumes/images), and
  return the co-tenants on teardown.

## Teardown

`kind delete cluster --name agentflow-staging`; co-tenant containers restarted from the
snapshot (`/tmp/agentflow_foreign_stopped.txt`). VM returned to ~5.3 GiB available.
