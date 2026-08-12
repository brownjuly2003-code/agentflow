# Live Iceberg materialization — 2026-08-01

**Date:** 2026-08-01

**Runtime source SHA:** `ed03fc47fa5f411016e588774d61a5b5eef21213`

**Audience:** developers and operations recording live verification evidence

**Result:** **PASS** (direct `events.validated` → lake materializer → Iceberg only)

## Goal and boundary

Prove that the current `ed03fc47` lake materializer, running against the live
Operator/Flink stand based on accepted SHA `36ed1ec`, materializes one
tenant-scoped event from `events.validated` into live Iceberg table
`agentflow.validated_events`, with that exact identity observed once.

### Claimed scope

- direct injection into `events.validated`
- current materializer image built from runtime source SHA `ed03fc47`
- append into live Iceberg `agentflow.validated_events`
- independent direct PyIceberg scan proving exact identity match count `1`

### Non-goals (not claimed)

- Kafka source → PyFlink → Iceberg full E2E (event was injected directly into
  `events.validated`)
- ClickHouse or API participation
- checkpoint restore / replay acceptance
- fresh four-hour soak or rollback on the golden topology
- external penetration test or GitHub Environment `npm` approval evidence
- Operator acceptance of `ed03fc47` (Operator evidence remains exact `36ed1ec`)
- production acceptance (`production.status` remains `candidate`)

## Runtime identity

| Item | Value |
|------|-------|
| Runtime source SHA | `ed03fc47fa5f411016e588774d61a5b5eef21213` |
| Operator / Flink stand base SHA | `36ed1ecc250ac6c82ccc6f27de1b76a301b17a41` |
| Cluster | `agentflow-golden-36ed1ec` |
| Context | `kind-agentflow-golden-36ed1ec` |
| Materializer image | `agentflow/api:ed03fc47-iceberg-live-20260801-01` |
| Image digest | `sha256:a759e00942bd8313b1ace06797087c0c84ee29990952a8d232fa0e3d81d5e6d2` |
| Compose project | `agentflow-iceberg-live-ed03fc47-01` |
| Compose images | `minio/minio:RELEASE.2025-09-07T16-13-09Z`, `tabulario/iceberg-rest:0.6.0` |
| Kind network gateway used by pods | `172.20.0.1` |
| Materializer Deployment | `agentflow-lake-materializer`, Available `1/1`, restarts `0` |
| Materializer group | `agentflow-iceberg-live-ed03fc47-20260801-01` |
| Offset reset | `latest` |
| Event id | `iceberg-live-ed03fc47-20260801-01` |
| Tenant | `acceptance` |
| Topic | `events.validated` (direct one-shot producer Job) |

## Prerequisites and protected stand

The live gate reused the Operator/Flink acceptance stand and did not upgrade
Helm or replace the accepted Operator topology.

| Protected post-state item | Value |
|---------------------------|-------|
| Helm release | revision `2` / deployed; no Helm upgrade or full chart apply |
| ServiceAccount UID | `a8f4ebd8-53de-4680-b89d-83d0114db852` |
| FlinkDeployment UID | `0622bd9c-3cec-410c-b778-78440a3c0ba9` |
| Flink job | RUNNING / READY, job id `0171cd969b5b300199c83dca620bd620` |
| Existing API / Redis / Kafka / Flink pods | Ready, restart count `0` |
| Local tracked tree before this documentation task | unchanged |

## Event and materializer evidence

| Step | Observation |
|------|-------------|
| Producer acknowledgement | `delivery_result=ACK event_id=iceberg-live-ed03fc47-20260801-01 tenant=acceptance topic=events.validated partition=0 offset=0` |
| Materializer log (`2026-08-01 11:29:47` UTC) | `lake_batch_materialized appended=1 consumed=1 duplicates=0` |

A Grok verification Job completed and proved identity presence via
`existing_event_identities()`. That helper returns a set and therefore does
**not** by itself prove absence of duplicate physical rows. It is supporting
presence evidence only, not the decisive exact-count proof.

## Independent verification (decisive)

Independent Codex verification used a direct PyIceberg table scan with
`EqualTo("event_id", ...)`, selected `tenant_id,event_id`, filtered the exact
tenant/event identity, and returned:

```text
event_id=iceberg-live-ed03fc47-20260801-01 tenant=acceptance match_count=1 result=PASS
```

The independent verifier container was task-scoped and removed after PASS.

## Limitations

- Claim is limited to:
  direct `events.validated` → current `ed03fc47` lake materializer → live
  Iceberg `agentflow.validated_events`, exact identity observed once.
- No Kafka source path, ClickHouse path, API path, restore/replay, soak,
  rollback, external pen-test, or npm Environment protection is claimed.
- Mixed-SHA boundary is intentional: Operator topology evidence remains exact
  `36ed1ec`; materializer runtime source is `ed03fc47`.
- Pre-evidence-commit repository HEAD remains `ed03fc47`; this documentation
  task does not invent a future commit hash.

## Resources intentionally left running

These remain for the next independent gate. Documented cleanup only; not run
by this task.

- Compose MinIO + Iceberg REST project `agentflow-iceberg-live-ed03fc47-01`
- Deployment `agentflow-lake-materializer`
- Completed producer / verify Jobs
- Isolated remote clone / bundle / render under `/tmp`

## Bounded cleanup (documentation only)

Do not run these as part of this claims task. Exact bounded cleanup for a later
authorized session:

```text
/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete job agentflow-iceberg-producer-ed03fc47-01 agentflow-iceberg-verify-ed03fc47-01 --ignore-not-found
/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete deployment agentflow-lake-materializer --ignore-not-found
/usr/local/bin/docker compose -p agentflow-iceberg-live-ed03fc47-01 -f /tmp/agentflow-iceberg-ed03fc47-20260801-01/docker-compose.iceberg.yml down -v
rm -rf /tmp/agentflow-iceberg-ed03fc47-20260801-01 /tmp/agentflow-ed03fc47-main.bundle /tmp/agentflow-iceberg-ed03fc47-20260801-01-render /tmp/agentflow-iceberg-producer-ed03fc47-01.yaml /tmp/agentflow-iceberg-verify-ed03fc47-01.yaml
```

Do not delete the kind cluster, Colima, Helm release, FlinkDeployment,
Kafka, API, Redis, or any other pre-existing stand resource.

## Next gate

Next safe atomic production gate:

1. Kafka → PyFlink → Iceberg → ClickHouse → API smoke

Still open after that:

2. checkpoint restore / replay without duplicate `(tenant_id, event_id)`
3. fresh golden-topology 4-hour soak + rollback
4. external penetration test with remediation / retest
5. GitHub Environment `npm` approval-protection evidence

Do not raise `production.status` above `candidate`.
