# Production CDC Source Onboarding

## Status

Production CDC onboarding is not enabled. The checked-in CDC path covers the
local/demo and Kubernetes-shaped staging primitives only (compose source DBs,
Kafka Connect image, connector registration, topic bootstrap, the
`helm/kafka-connect` chart with a values schema, and integration tests).

This runbook defines the decision record, preflight checks, and rollout /
rollback procedure required before attaching a real Postgres or MySQL source to
AgentFlow. Enabling a live source requires external inputs — source ownership,
credentials, network path, and approvals — that are supplied and approved
outside the repository. Do not create production connectors until every required
input below is filled and approved by the source-system owner, platform owner,
and security owner.

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

## Chart hardening baseline

The `helm/kafka-connect` chart ships with the same hardening primitives as
`helm/agentflow`, off-by-default so existing clusters do not break, but
ready to enable per environment:

| Primitive | Values key | Default | Production recommendation |
|-----------|------------|---------|---------------------------|
| Pod securityContext (non-root, fsGroup) | `podSecurityContext` | `runAsNonRoot=true, runAsUser=1000` | Keep defaults; Confluent base image runs as UID 1000 |
| Container securityContext (read-only FS, drop ALL caps) | `containerSecurityContext` | `readOnlyRootFilesystem=true, capabilities.drop=[ALL]` | Keep defaults |
| `/tmp` scratch (required when root FS is read-only) | `tmpVolume` | `enabled=true, sizeLimit=256Mi` | Keep defaults; raise sizeLimit only if Connect plugin extraction needs more |
| PodDisruptionBudget | `podDisruptionBudget` | `enabled=true, minAvailable=1` | Keep `minAvailable=1` for `replicaCount<=2`; raise to `minAvailable=2` once `replicaCount>=3` |
| NetworkPolicy default-deny | `networkPolicy.enabled` | `false` | **Set to `true` in production** to lock down egress to Kafka brokers + source DBs only |
| NetworkPolicy egress ports | `networkPolicy.egressPorts` | `kafka=9092, postgres=5432, mysql=3306` | Update if production uses non-default ports |
| NetworkPolicy ingress | `networkPolicy.ingressFromNamespaces` | `monitoring` only | Add Prometheus/scrape namespace and any pod that needs the Connect REST API |

The `values.schema.json` requires all of the keys above; `helm install` and
`helm lint` fail closed if production values omit them. The
`tests/integration/test_helm_values_live_validation.py` parametrized live
validation covers both `helm/agentflow` and `helm/kafka-connect` against a
real cluster, and accepts a reusable external context via
`AGENTFLOW_LIVE_REUSE_CLUSTER=1` (see `conftest.kind_cluster`).

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
