# Full lake-to-serving single-event smoke — 2026-08-01

**Date:** 2026-08-01

**Runtime source SHA:** `ed03fc47fa5f411016e588774d61a5b5eef21213`

**Audience:** developers and operations recording live verification evidence

**Result:** **PASS** (mixed-SHA single-event full hop chain)

**Evidence commit status:** recorded in local evidence commit
`cf247bad7015320541814d47f406507a218b2f05` (`docs: record full lake-to-serving smoke`;
local-only, unpushed). That SHA is evidence/claims documentation only — **not** a
runtime or Operator-accepted SHA. Pre-gate/pre-evidence local base remains
`9070ec3d0c04b7b663e12f92e0d524e340cc7399` (local-only, unpushed; **not** current HEAD).

## Goal and boundary

Prove that one tenant-scoped event travels the complete measured hop chain on
the live mixed-SHA stand:

`orders.raw` → accepted `36ed1ec` PyFlink → `events.validated` → live Iceberg
`agentflow.validated_events` and, from the same validated event, serving
bridge → task ClickHouse `pipeline_events` / `orders_v2` → task ClusterIP API
entity + timeline.

“Full” means the complete measured hop chain for **one event**. It does **not**
mean full production acceptance, same-SHA Operator acceptance of `ed03fc47`,
multi-tenant acceptance, checkpoint restore/replay, soak, rollback, external
penetration test, or GitHub Environment `npm` approval.

The narrower direct-Iceberg gate
([live-iceberg-materialization-2026-08-01.md](live-iceberg-materialization-2026-08-01.md))
remains valid and is now complemented by this full one-event path.

### Claimed scope

- one event produced to `orders.raw`
- accepted Operator/Flink topology base `36ed1ec` processes it into
  `events.validated` with tenant stamped by PyFlink as `default`
- current `ed03fc47` lake materializer appends exact identity once into live
  Iceberg `agentflow.validated_events`
- current `ed03fc47` serving bridge applies the same validated event into task
  ClickHouse (`pipeline_events` + `orders_v2`)
- task ClusterIP API returns matching entity and timeline
- independent Codex re-verification of the same hop counters returns PASS

### Non-goals (not claimed)

- Operator acceptance of runtime source `ed03fc47` (Operator evidence remains
  exact `36ed1ec`)
- multi-tenant acceptance
- checkpoint restore / replay without duplicate `(tenant_id, event_id)`
- fresh four-hour soak or rollback on the golden topology
- external penetration test or GitHub Environment `npm` approval evidence
- production acceptance (`production.status` remains `candidate`)

## Runtime identity

| Item | Value |
|------|-------|
| Runtime source / `origin/main` | `ed03fc47fa5f411016e588774d61a5b5eef21213` |
| Local evidence commit (full-smoke claims) | `cf247bad7015320541814d47f406507a218b2f05` (local-only, unpushed; evidence/claims only — **not** runtime/Operator SHA) |
| Pre-gate/pre-evidence local base | `9070ec3d0c04b7b663e12f92e0d524e340cc7399` (local-only, unpushed; **not** current HEAD; **not** runtime/Operator SHA) |
| Operator / Flink stand base | `36ed1ec` |
| Cluster / context | `agentflow-golden-36ed1ec` / `kind-agentflow-golden-36ed1ec` |
| Namespace | `agentflow` |
| Image | `agentflow/api:ed03fc47-iceberg-live-20260801-01` |
| Image digest | `sha256:a759e00942bd8313b1ace06797087c0c84ee29990952a8d232fa0e3d81d5e6d2` |
| Route / model | `local_grok_cli` / actual `grok-4.5-build` |
| Grok run | `de-full-e2e-live-execute-continue-20260801-01` |
| Grok session | `019fbd54-973a-7432-9de8-ad127c47ff18` (stop `EndTurn`) |
| Task ClickHouse image | `clickhouse/clickhouse-server:24.8` |
| Task ClickHouse publish | `172.20.0.1:8123:8123` only |
| Event id | `8c1f16a0-e2e0-4a01-8d01-000000000001` |
| Order id | `ORD-20260801-950001` |
| User id | `USR-950001` |
| Tenant (after PyFlink) | `default` |
| Event type | `order.created` |
| Total | `209.97 USD` |
| Source topic | `orders.raw` |
| Validated topic | `events.validated` |

## Exact hop chain

1. Producer → `orders.raw`
2. Accepted `36ed1ec` PyFlink → `events.validated` (tenant stamped `default`)
3. Lake materializer → Iceberg `agentflow.validated_events`
4. Serving bridge → ClickHouse `pipeline_events` / `orders_v2`
5. Task ClusterIP API → entity + timeline for the same identity

## Job timeline (UTC, each succeeded once)

| Job | Window (UTC) | Outcome |
|-----|--------------|---------|
| Provision | `12:45:26Z`–`12:45:41Z` | succeeded; log `provision_schema_applied backend=clickhouse` |
| Producer | `12:49:36Z`–`12:49:41Z` | succeeded; ACK to `orders.raw` |
| Verifier | `12:49:54Z`–`12:50:16Z` | succeeded; full hop PASS |

## Observed hop evidence

| Hop | Observation |
|-----|-------------|
| Producer → `orders.raw` | `delivery_result=ACK event_id=8c1f16a0-e2e0-4a01-8d01-000000000001 order_id=ORD-20260801-950001 topic=orders.raw partition=0 offset=0` |
| Kafka validated / DLQ | `kafka_validated=1`, `kafka_deadletter=0`, tenant `default` |
| Lake materializer | `lake_batch_materialized appended=1 consumed=1 duplicates=0` |
| Iceberg scan | `iceberg_match=1` on `agentflow.validated_events` for exact tenant/event |
| Serving bridge | `bridge_batch_applied consumed=1 applied=1 duplicates=0 dead_lettered=0` |
| ClickHouse | `ch_pipeline=1`, `ch_orders=1` |
| Task API | Ready/Available `1/1`, ClusterIP only; `api_entity=1`, `api_timeline=1` |
| Task ClickHouse | image `clickhouse/clickhouse-server:24.8`, running/healthy, only `172.20.0.1:8123:8123`; reachable from kind node/pods |

### Grok verifier exact line

```text
event_id=8c1f16a0-e2e0-4a01-8d01-000000000001 order_id=ORD-20260801-950001 tenant=default kafka_validated=1 kafka_deadletter=0 iceberg_match=1 ch_pipeline=1 ch_orders=1 api_entity=1 api_timeline=1 result=PASS
```

### Independent Codex verifier exact result

```json
{"api_entity": 1, "api_timeline": 1, "ch_orders": 1, "ch_pipeline": 1, "event_id": "8c1f16a0-e2e0-4a01-8d01-000000000001", "iceberg_match": 1, "iceberg_table": "agentflow.validated_events", "kafka_deadletter": 0, "kafka_validated": 1, "order_id": "ORD-20260801-950001", "result": "PASS", "tenant": "default"}
```

## Task-artifact correction (one)

`AGENTFLOW_PROCESS_ROLE=api` is rejected by the embedded control plane without
postgres on this image. The task API Deployment alone was changed to
`AGENTFLOW_PROCESS_ROLE=all` (embedded single-process shape that still serves
requests). No protected resource and no product code changed.

## Protected post-state (unchanged)

| Resource | Value |
|----------|-------|
| Helm release | revision `2` / deployed |
| ServiceAccount UID | `a8f4ebd8-53de-4680-b89d-83d0114db852` |
| FlinkDeployment UID | `0622bd9c-3cec-410c-b778-78440a3c0ba9` |
| Flink job | `0171cd969b5b300199c83dca620bd620` RUNNING / STABLE |
| Lake materializer | Available `1/1` |
| Protected pod restarts | `0` |

No Helm upgrade and no patch/restart of protected Flink, Kafka, Redis, API, or
materializer.

## Provenance hashes (SHA-256)

| Artifact | SHA-256 |
|----------|---------|
| Grok stdout JSON | `F50594C222DB78FED60D848C7116B5F717C91AC3CE8852CBBF786ED4CFD09294` |
| Continuation prompt | `E95B525420A70B55DBF6F5C303989BD171144A5A1554C3014253C217EF6234B8` |
| `clickhouse-compose.yml` | `D78C067BEA241CE6F0A7C1DD2032333CA1E2DB433774090B71A1D95D30948E1E` |
| `provision-job.yaml` | `B6DD6855AACDC757B63A2F7B463C2D2E9FE93625520433F7F5D1CD8D7664F1FD` |
| `bridge-deployment.yaml` | `CF84EA8146DF5594AB70FCEDF2944501802F0E01EDBE9E06292273A003BB1413` |
| `api-deployment.yaml` | `5E1F6BAD6F1F59EE9C3B2E4EB29DAA444F3AD4E1DA7BF984429D3EBF50F5E0BA` |
| `producer-job.yaml` | `259E91F0973306FD90E1BEF4E52FA5B11904DA11DBC98EED6094664A1C5D241F` |
| `verify-job.yaml` | `455C5D082B8C41E986F42CD2B7D94C6652BE36F93488DD6C3AB1F5305A2E418C` |
| `runtime-result.md` | `AA85F7D42677468CA788C4C630DB5C8B5441A11A389CC2C05AF9AF2AF91DC668` |
| Independent verifier | `6DFA0DEDCD90403F2B0FE925069662DFBC0FBE5A6B17C86E068B145AABD84742` |

Control artifacts live under
`.codex-grok-tasks/full-e2e-live-20260801/` (local only) with remote copies
under `/tmp/agentflow-full-e2e-ed03fc47-20260801-01/`.

## Limitations

- Mixed-SHA boundary is intentional: Operator/Flink topology evidence remains
  exact `36ed1ec`; serving/materializer/API runtime source is `ed03fc47`.
- Single-event smoke only; not multi-tenant, restore/replay, soak, rollback,
  pen-test, or npm Environment protection.
- Task API uses `AGENTFLOW_PROCESS_ROLE=all` rather than split `api` because the
  embedded control plane rejects `api` without postgres.
- Host-side curl to `172.20.0.1:8123` does not work on Docker Desktop Mac;
  kind-node and in-cluster paths do (same pattern as the prior Iceberg gate).
- Tracked full-smoke evidence is recorded in local evidence commit `cf247ba`
  (full SHA above; local-only, unpushed). This metadata sync does not invent a
  future commit hash.

## Resources intentionally left running

Resources remain for follow-on verification. Do **not** clean them up from a
claims-only task.

- Docker project `agentflow-ch-e2e-ed03fc47-01` + volume
- Deployments: task bridge + task API (Ready/Available `1/1`)
- Service: task API ClusterIP
- Completed Jobs: provision, producer, verify
- Remote dir `/tmp/agentflow-full-e2e-ed03fc47-20260801-01`
- Existing Iceberg Compose `agentflow-iceberg-live-ed03fc47-01`, materializer,
  and prior Iceberg Jobs (not part of this task’s cleanup)

## Bounded cleanup (documentation only — do not run on PASS)

Copied from `.codex-grok-tasks/full-e2e-live-20260801/runtime-result.md`.
Target only this task’s resources:

```bash
# Kubernetes task resources
/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete job agentflow-e2e-verify-ed03fc47-01 --ignore-not-found
/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete job agentflow-e2e-producer-ed03fc47-01 --ignore-not-found
/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete job agentflow-e2e-provision-ed03fc47-01 --ignore-not-found
/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete deploy agentflow-e2e-serving-bridge-ed03fc47-01 --ignore-not-found
/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete deploy agentflow-e2e-api-ed03fc47-01 --ignore-not-found
/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete svc agentflow-e2e-api-ed03fc47-01 --ignore-not-found

# Task ClickHouse only
/usr/local/bin/docker compose -p agentflow-ch-e2e-ed03fc47-01 -f /tmp/agentflow-full-e2e-ed03fc47-20260801-01/clickhouse-compose.yml down -v

# Remote task dir
/bin/rm -rf /tmp/agentflow-full-e2e-ed03fc47-20260801-01
```

**Warning:** do **not** delete the kind cluster, Helm release, FlinkDeployment,
Kafka, Redis, protected API, Iceberg Compose
`agentflow-iceberg-live-ed03fc47-01`, lake materializer, prior Iceberg
producer/verify Jobs, or local control-directory evidence under
`.codex-grok-tasks/full-e2e-live-20260801/`.

## Next gate

Next safe atomic production gate:

1. checkpoint restore and replay without duplicate `(tenant_id, event_id)`

Still open after that:

2. fresh 4 h soak + rollback on the golden topology
3. external penetration test with remediation / retest
4. GitHub Environment `npm` approval-protection evidence

Overall production-acceptance gates remaining: **exactly four** (the two
repository-side pending items above plus external pentest and npm approval).

Do not raise `production.status` above `candidate`.
