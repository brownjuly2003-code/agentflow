# Production CDC Source Onboarding

## Status

Production CDC onboarding is not approved yet. This runbook defines the
decision record and preflight checks required before attaching real Postgres or
MySQL sources to AgentFlow.

Do not create production connectors until every required input below is filled
and approved by the source-system owner, platform owner, and security owner.

## Required Decision Record

| Field | Required value |
|-------|----------------|
| Source owner | Team and escalation contact for the database |
| Secret owner | Team that creates, rotates, and revokes the CDC user credentials |
| Source engine | Postgres or MySQL, including version |
| Hostname and port | Production endpoint reachable from Kafka Connect |
| Database name | Exact database name |
| Table scope | Explicit schema/table allowlist; no wildcard production rollout |
| Data classification | PII, financial, operational, or public |
| Initial snapshot policy | Full snapshot, incremental snapshot, or schema-only start |
| Maintenance window | Approved start time and rollback window |
| Network path | VPC peering, private link, VPN, or in-cluster route |
| Kafka Connect Secret | Existing Kubernetes Secret name and owner |
| Monitoring owner | Team that watches connector lag, failures, and dead letters |
| Rollback owner | Person allowed to pause/delete the connector |

## Preflight Checks

1. Confirm the source database has a dedicated CDC user with least-privilege
   access to only the approved tables.
2. Confirm production credentials are stored in an externally managed
   Kubernetes Secret. Do not commit production credentials or render them from
   Helm values.
3. Confirm network reachability from the Kafka Connect namespace to the source
   host and port.
4. Confirm the raw topic names match the canonical
   `cdc.<source>.<schema>.<table>` contract used by the normalizer.
5. Confirm Kafka topics exist before connector start. Kafka auto-create should
   stay disabled.
6. Confirm expected row volume, snapshot size, and replication lag budget.
7. Confirm the source owner has approved binlog or logical replication settings.
8. Confirm dead-letter and connector status dashboards are watched during the
   first snapshot.

## No-Go Conditions

Stop before connector creation if any condition is true:

- The table scope uses a wildcard or includes tables not reviewed for data
  classification.
- The credential owner cannot rotate or revoke the CDC user on demand.
- The source database is reachable only over a public network path.
- The Kafka Connect Secret would be generated from committed production values.
- The source owner has not approved replication slot, binlog, or snapshot load.
- No operator is assigned to monitor the initial snapshot.

## Rollout

1. Render the Kafka Connect chart with externally managed source credentials:

```bash
helm template agentflow-kafka-connect helm/kafka-connect \
  --set secrets.create=false \
  --set secrets.existingSecret=<existing-secret-name>
```

2. Validate the rendered manifest does not contain credential values.
3. Apply the connector during the approved maintenance window.
4. Watch connector status until every task is `RUNNING`:

```bash
curl -fsS http://<connect-host>:8083/connectors/<connector-name>/status
```

5. Watch Kafka lag, Debezium heartbeat topics, AgentFlow dead letters, and
   serving-layer freshness.
6. Record the first successful normalized event and the first serving-layer read
   that depends on the new source.

## Rollback

If snapshot load, lag, or dead-letter volume exceeds the approved threshold:

1. Pause the connector:

```bash
curl -fsS -X PUT http://<connect-host>:8083/connectors/<connector-name>/pause
```

2. If the source owner requests full detach, delete the connector:

```bash
curl -fsS -X DELETE http://<connect-host>:8083/connectors/<connector-name>
```

3. Revoke or rotate the CDC credential if exposure is suspected.
4. Keep raw topics until the incident owner decides whether they are needed for
   replay or forensic review.

## Evidence to Capture

- Completed decision record.
- Connector status response showing `RUNNING`.
- Topic list showing expected raw and heartbeat topics.
- First normalized event sample with secrets and PII redacted.
- Dead-letter count before and after onboarding.
- Freshness and lag screenshots or metric exports from the first hour.
