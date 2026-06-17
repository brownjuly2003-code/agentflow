# CDC Lag / Stuck Connectors

**Last updated:** 2026-05-24

## Symptom

One or more of:

- Grafana panel `agentflow / CDC lag` shows a Kafka Connect connector with
  lag growing monotonically for ≥ 10 minutes.
- `kafka-connect` REST API reports a connector `state=FAILED` or one of its
  tasks `state=FAILED`.
- Dead-letter topic depth (`agentflow.cdc.dlq.*`) climbing.
- Downstream consumers report stale entity reads — `/v1/entity/...` returns
  data that does not reflect a write from > 5 minutes ago.

## Severity

Default **Sev 2**. Escalate to **Sev 1** if:

- Lag exceeds the freshness SLO promised to any customer (default contract:
  entity reads ≤ 60s behind source) for > 30 minutes.
- DLQ growth indicates structural deserialization failure — every event after
  a schema change is being rejected.
- The source database itself is unreachable from Kafka Connect and the gap
  cannot be closed by topic replay alone.

## Owner

Data on-call. Loop in source-system owner (recorded in
`docs/operations/cdc-production-onboarding.md` § "Required Decision Record")
if the symptom is upstream of Kafka Connect.

## Detection

1. Kafka Connect REST API:
   ```
   kubectl -n <ns> port-forward svc/kafka-connect 8083:8083 &
   curl -s http://localhost:8083/connectors | jq
   for c in $(curl -s http://localhost:8083/connectors | jq -r '.[]'); do
     curl -s http://localhost:8083/connectors/$c/status | jq '{name, connector:.connector.state, tasks:[.tasks[]|{id, state, trace:.trace[0:200]}]}'
   done
   ```
2. Consumer lag (per connector group):
   ```
   kubectl -n <ns> exec -it deployment/kafka -- \
     kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
     --describe --group connect-<connector-name>
   ```
3. DLQ depth:
   ```
   kubectl -n <ns> exec -it deployment/kafka -- \
     kafka-run-class.sh kafka.tools.GetOffsetShell \
     --broker-list localhost:9092 --topic agentflow.cdc.dlq.<source>
   ```
4. Source-DB health: Postgres replication slot lag, MySQL binlog position vs.
   current GTID.

## Triage

1. **Which connector?** Single connector or every connector. Single = scoped
   to that source DB. Every = Kafka Connect cluster issue (network, broker,
   resource).
2. **FAILED vs. slow?** A `FAILED` task has a stack trace and a specific
   root cause to fix. A `RUNNING` task with growing lag is a throughput problem.
3. **DLQ depth growing?** If yes, recent events are being dropped. Pull the
   last 10 DLQ messages — most CDC DLQ growth is one of:
   - Schema evolution the connector cannot handle (column type widened, new
     NOT NULL column).
   - Source row exceeds the configured max message size.
   - Auth token expired / rotated on the source side.
4. **Replication slot stuck?** For Postgres:
   ```
   psql -h <src> -c "SELECT slot_name, active, restart_lsn, confirmed_flush_lsn,
     pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS lag
     FROM pg_replication_slots WHERE slot_name LIKE 'agentflow_%';"
   ```
   A non-active slot with growing lag will eventually fill the source WAL
   disk — this is its own Sev 1 if the source DB is in danger.
5. **DV2 demo cluster?** If the alert came from the Lima/iMac demo cluster,
   the connector is `MaterializedPostgreSQL` (ClickHouse-side), not Kafka
   Connect. See `infrastructure/dv2/clickhouse/cdc_setup.sql` and the
   per-branch CDC fan-out notes in `docs/dv2-multi-branch/`.
   That cluster does **not** have on-call — escalate to demo owner instead of
   following the production mitigation steps below.

## Mitigation

### Single connector FAILED — restart task

```
curl -s -X POST http://localhost:8083/connectors/<name>/restart?includeTasks=true&onlyFailed=true
```

Then re-check status after 30 seconds. If the same task fails again with the
same trace, the restart is not the fix — proceed to root cause.

### DLQ growth from schema drift

Stop the connector, capture the offending event, evolve the schema or the
sink mapping, then resume from the recorded offset:

```
curl -X PUT http://localhost:8083/connectors/<name>/pause
kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic agentflow.cdc.dlq.<source> --from-beginning --max-messages 5
# fix schema / sink mapping in helm/kafka-connect overrides
helm upgrade kafka-connect helm/kafka-connect -f values-<env>.yaml
curl -X PUT http://localhost:8083/connectors/<name>/resume
```

### Source DB unreachable

If the source DB is the cause, do **not** restart the connector in a loop —
each restart resets state and may force a re-snapshot that the source cannot
handle. Pause the connector:

```
curl -X PUT http://localhost:8083/connectors/<name>/pause
```

Engage the source-system owner (per onboarding decision record). The
connector will resume from the last committed offset on un-pause; nothing is
lost as long as the source replication slot is preserved.

### Stuck replication slot threatening source WAL

If source DB WAL disk is at risk, two paths:

1. Resume the consumer (fastest if achievable in < 5 minutes).
2. Drop the slot and re-snapshot — **destroys gap data**. Only acceptable if
   downstream can tolerate it, otherwise the source DB itself becomes Sev 1.

```
# Last-resort, data-loss path. Requires source-system owner approval.
psql -h <src> -c "SELECT pg_drop_replication_slot('agentflow_<name>');"
# Re-create connector to re-snapshot.
```

### Cluster-wide Kafka Connect issues

Lag on every connector:

- Pod restart count climbing → scale up replicas / check resources:
  ```
  kubectl -n <ns> scale deployment/kafka-connect --replicas=<current+1>
  kubectl -n <ns> top pods -l app.kubernetes.io/name=kafka-connect
  ```
- Broker-side throttling → check Kafka broker disk / CPU.
- Connect cluster restarted (rebalance loop) → wait one rebalance interval
  (default 60s) before further action.

## Resolution

1. All connectors are `RUNNING` with `tasks[*].state = RUNNING`.
2. Lag is decreasing and within freshness SLO for ≥ 10 minutes.
3. DLQ depth is constant (not growing) — historical DLQ depth from past
   incidents does not need to be drained, but new events stopped arriving.
4. Replication slots on source DBs are `active=t` and `lag` shrinking.
5. Open a follow-up issue if root cause was schema-drift — produce a
   ClassMap / schema-registry change so the same drift cannot recur silently.

## Postmortem trigger

- Mandatory if data was actually lost (slot drop, DLQ drained without replay,
  source rollback).
- Mandatory if lag exceeded freshness SLO for any tenant.
- Recommended for any FAILED → RESTART cycle that needed > 2 attempts to
  recover.
