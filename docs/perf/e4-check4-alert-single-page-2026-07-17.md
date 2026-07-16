# E4 Checks 1–4 — full replica-correctness live (kind)

> Executed: `2026-07-16` UTC / local `2026-07-17` on `deproject-mac` (kind + Docker
> on Colima vz, 6 GiB / 4 CPU, macOS 13.7.x Intel). Code: local `main` tip with
> Check 3–4 automation + enqueue-lease fix (pre-push; base `22fbae6` + ahead
> commits including this session). Completes cutover-plan Phase 3 topology proof
> for alert single-page (**Check 4**) on top of Checks 1–3.

## Result

`scripts/k8s_replica_correctness_verify.sh` → **exit 0, Checks 1–4 PASS**:

```
PASS: 2 ready pods, all AGENTFLOW_CONTROLPLANE_STORE=postgres
PASS: webhook visible on all 8 round-robin reads across pods
PASS: exactly one delivery_id for event_id=replica-e4-57b29e2b5f1e465f (1 log row(s))
PASS: exactly one alert.triggered page for alert_id=845d0528-ad3c-4143-9437-e582ad0b89c3 (1 history row(s))
==> replica-correctness verify OK (Checks 1-4)
```

| Check | Proof |
|-------|--------|
| **1** | `deployment/agentflow` 2/2 Ready; every Running API pod has `AGENTFLOW_CONTROLPLANE_STORE=postgres` |
| **2** | webhook `07a1fc94-83a6-4f30-a331-d6e7a6028488` registered through the Service visible on all 8 round-robin list reads |
| **3** | one CH `pipeline_events` row (`event_id=replica-e4-57b29e2b5f1e465f`); `GET /v1/webhooks/{id}/logs` → **one** `delivery_id`; queue row `status=delivered`, `last_status_code=200` |
| **4** | alert `845d0528-ad3c-4143-9437-e582ad0b89c3` (`error_rate` below 1.0 / 1h); history → **exactly one** successful `alert.triggered` |

## Topology

- kind cluster `agentflow-staging` (`kindest/node:v1.32.2`), NodePort **30080 → host 8080**.
- Chart: `helm/agentflow` + `values-staging.yaml` + scale overlay
  (`replicaCount=2`, `persistence.enabled=false`, CH + postgres control plane,
  CH user `agentflow`).
- In-cluster: PostgreSQL 16, ClickHouse 24.8, Redis 7.4 + secrets
  `agentflow-controlplane-pg` / `agentflow-clickhouse`.
- Image: `agentflow/api:staging` with `.[postgres]` + `pyiceberg`.
- SA is a chart pre-hook (weight `-10`); provision Job completed without manual SA create.
- Webhook target: `https://httpbin.org/post` (POST 2xx; see gotcha below).

## Gotchas found this run

1. **Enqueue vs redrive race (fixed).** First attempt with the pre-fix image
   produced **two** `delivery_id`s 13 ms apart for one queue row: the insert-win
   worked (PK uniqueness), but the winner did not stamp `lease_expires_at` on
   enqueue, so the other pod's `process_delivery_queue` claimed the still-pending
   row mid-inline POST. Fix: `PostgresControlPlaneStore.enqueue_webhook_delivery`
   stamps the same claim lease as `claim_due_*`; outcome or lease expiry releases
   it. Live re-run after rebuild: one delivery, `delivered` / 200.
2. **`example.com` rejects POST (405).** Default `WEBHOOK_URL` is now
   `https://httpbin.org/post`. A 405 forces redrive and a second `delivery_id`,
   which the exactly-one assertion would mis-read as split delivery.
3. **Alert wait.** `ALERT_WAIT_SECONDS=180` (dispatcher poll 60s) was enough for
   Check 4 on this stand.

## Reproduce

```bash
export PATH=$HOME/bin:/usr/local/bin:$PATH
# colima start (4 CPU / 6 GiB / vz); co-tenants left stopped
# kind + PG/CH/Redis + scale helm as in e4-check3 / this session bring-up
BASE_URL=http://127.0.0.1:8080 \
  CLICKHOUSE_USER=agentflow \
  ALERT_WAIT_SECONDS=180 \
  bash scripts/k8s_replica_correctness_verify.sh
```

## Teardown

`kind delete cluster --name agentflow-staging` (optional: `colima stop`).
Do **not** `docker system prune` — co-tenant named volumes must stay.

## Status

**E4 automated topology proof: PASS (Checks 1–4).** Delivery exactly-once and
alert single-page are closed at the two-real-pods topology layer. Phase 3 of the
cutover plan is complete for the automated checks.
