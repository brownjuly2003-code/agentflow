# E4 Check 3 — exactly-one webhook delivery (topology, kind)

> Executed: `2026-07-16` on `deproject-mac` (kind + Docker on Colima vz, 6 GiB / 4 CPU,
> macOS 13.7.x Intel). Code base: `main` @ `22fbae6` (+ local Check 3 verify script).
> Completes the delivery half of cutover-plan Phase 3 / STATUS “delivery topology”
> that Checks 1–2 left open in [e4-replica-topology-2026-07-11.md](e4-replica-topology-2026-07-11.md).

## Result

`scripts/k8s_replica_correctness_verify.sh` → **exit 0, Checks 1–3 PASS**:

```
PASS: 2 ready pods, all AGENTFLOW_CONTROLPLANE_STORE=postgres
PASS: webhook visible on all 8 round-robin reads across pods
PASS: exactly one delivery_id for event_id=replica-e4-858cce874ac04494 (1 log row(s))
```

- **[Check 1]** `deployment/agentflow` 2/2 Ready; every Running API pod carries
  `AGENTFLOW_CONTROLPLANE_STORE=postgres`.
- **[Check 2]** webhook `0c5e87f9-9dd5-44f5-b2f6-5b9961f9d04e` registered through the
  Service was visible on all 8 round-robin list reads.
- **[Check 3]** one `pipeline_events` row inserted into the shared ClickHouse journal
  (`event_id=replica-e4-858cce874ac04494`, tenant `default`); both pods’ scanners raced
  durable enqueue; `GET /v1/webhooks/{id}/logs` showed **exactly one** distinct
  `delivery_id` (insert-win — only the enqueue winner POSTs).

Alert single-page (cutover Phase 3 item 3) is now **Check 4** in
`scripts/k8s_replica_correctness_verify.sh` (post this run). Store-level
`claim_alert_tick` is already proven 31/31 in
[control-plane-pg-verify-2026-07-03.md](control-plane-pg-verify-2026-07-03.md);
two-pod emission evidence still needs a scale-stand re-run with Checks 1–4.

## Topology

- kind cluster `agentflow-staging` (`kindest/node:v1.32.2`), `k8s/kind-config.yaml`
  (NodePort **30080 → host 8080**).
- Chart: `helm/agentflow` with `values-staging.yaml` + scale overlay
  (`replicaCount=2`, `persistence.enabled=false`, `serving.backend=clickhouse`,
  `controlPlane.store=postgres`, CH user `agentflow`).
- In-cluster deps: PostgreSQL 16 (`agentflow-postgres`), ClickHouse 24.8
  (`agentflow-clickhouse`), Redis 7.4 (`agentflow-redis`) + secrets
  `agentflow-controlplane-pg` / `agentflow-clickhouse`.
- Image: `agentflow/api:staging` built with `.[postgres]` **and** `pyiceberg`
  (import-time hard dep of `HealthCollector`).
- Access: `BASE_URL=http://127.0.0.1:8080` (kind extraPortMapping).

## Stand notes (this run)

1. **Colima was stopped** — `colima start` (existing 4 CPU / 6 GiB / vz profile).
   Co-tenant containers were already Exited; left stopped for RAM headroom.
2. **Provision Job vs ServiceAccount** — pre-install hook `agentflow-provision`
   references SA `agentflow`, but on this run the SA was not yet a helm hook
   resource, so the first install sat in `pending-install` until the SA was
   created manually. After that the job completed
   (`provision_schema_applied backend=clickhouse`). **Fixed in chart:** SA is now
   a `pre-install,pre-upgrade` hook with weight `-10` (Job stays `-5`); no
   out-of-band `kubectl create sa` needed on next staging bring-up.
3. **Image must include `pyiceberg`** — without it pods CrashLoop with
   `ModuleNotFoundError: No module named 'pyiceberg'` at import of
   `metrics_collector`. Staging Dockerfile / `k8s_staging_up` build context should
   keep that install (matches earlier e4 stage1c practice).
4. **Check 1 pod selector** — provision Job pods share
   `app.kubernetes.io/instance=agentflow` but have no control-plane env. Verify
   script now lists only `status.phase=Running` pods so Completed Jobs are ignored.
5. **Check 3 automation** — CH insert via `clickhouse-client` on the in-cluster
   pod; delivery target `https://example.com/agentflow-replica-verify` (public,
   2xx, no redrive noise). Assertion is distinct `delivery_id` count for the
   injected `event_id`, not attempt-row count.

## Reproduce

```bash
export PATH=$HOME/bin:/usr/local/bin:$PATH
# colima start; kind cluster + PG/CH/Redis + scale helm as above
# image: pip install -e ".[postgres]" && pip install pyiceberg
# SA is a chart pre-hook (weight -10); no manual create needed on current main
BASE_URL=http://127.0.0.1:8080 \
  CLICKHOUSE_USER=agentflow \
  bash scripts/k8s_replica_correctness_verify.sh
```

## Teardown

`kind delete cluster --name agentflow-staging` (optional: `colima stop`).
Do **not** `docker system prune` — co-tenant named volumes must stay.

## Status

**E4 automated topology proof: PASS (Checks 1–3).** Delivery exactly-once across
two real pods is closed at the topology layer. Alert single-page automation
landed later as Check 4; re-run the full script on the scale stand for evidence.
