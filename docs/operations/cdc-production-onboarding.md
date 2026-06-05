# Production CDC Source Onboarding

## Status

Reopened on 2026-06-05 (second operator decision, «давай сделаем то, что
возможно»): a real production source DOES exist in the operator's own estate —
the Neon Postgres project backing VacancyRadar (`public.vacancies`, ~95k live
rows, PostgreSQL 17). The decision record below is filled with solo-org owners
(a one-person organization is recorded honestly as such). Evidence channel:
the dispatch-only `cdc-production-capture.yml` workflow + repository Actions
secrets + `scripts/capture_production_cdc.sh` (initial-snapshot capture with
unconditional teardown of connector, publication, and replication slot).

Remaining external step before the first run: the operator must enable
Logical Replication on the Neon project (Console → Project settings →
Logical Replication → Enable, or via a Neon API key). The flip is
IRREVERSIBLE (`wal_level` stays `logical`) and restarts project computes;
VacancyRadar writers reconnect on their next run. Verified live on
2026-06-05: `wal_level=replica`, 1 pre-existing managed replication slot
(must not be touched; the capture script drops only its own
`agentflow_prod_capture_slot`).

## Decision record (2026-06-05, solo-org)

- Source owner and escalation contact: Julia Edomskikh (operator).
- Secret owner: Julia Edomskikh; connection material lives only in repository
  Actions secrets (`CDC_NEON_HOSTNAME/USER/PASSWORD/DBNAME`) and the local
  VacancyRadar `.env`.
- Source engine and scope: Neon Postgres 17 (aarch64), database `neondb`,
  approved table scope `public.vacancies` only.
- Network path: public TLS endpoint (`sslmode=require`); no private network
  exists or is claimed.
- Kubernetes Secret owner: not applicable — the capture path runs in CI, not
  in the Helm deployment; the Helm production secret mode remains documented
  below for a future real cluster.
- Monitoring owner: Julia Edomskikh; monitoring scope for the evidence run is
  the workflow run log plus connector status captured into the evidence
  artifact.
- Rollback owner: Julia Edomskikh; rollback procedure is encoded in the
  capture script teardown trap (delete connector, drop publication, drop
  `agentflow_prod_capture_slot`, verify zero leftover capture slots) and
  runs even when capture fails.

## Planned retry (next session)

The 2026-06-05 autonomous attempt to enable Logical Replication from the
operator's iMac via a CDP-driven real Chrome session reached the Google
password + 2FA stage (credentials and the bot-block bypass both worked) but
could not complete: the free AdGuard VPN kept dropping the non-RU egress
(Neon unreachable for most of each window) and the 8 GB Intel iMac killed the
detached login process under Chrome load. The wall was environmental
connectivity, not credentials or logic.

**2026-06-05 follow-up — the option-2 API question is RESOLVED.** Enabling
Logical Replication is NOT Console-only: the public Neon API exposes it as a
first-class project setting (`settings.enable_logical_replication`, verified
against the Neon API reference + TypeScript SDK). A single
`PATCH https://console.neon.tech/api/v2/projects/{project_id}` performs the
same irreversible `wal_level=logical` flip + compute restart as the Console
button (exact command in option 2). So the only step that still strictly needs
an authenticated Console browser session is *creating an API key* — the flip
itself does not.

Next attempt, in preference order:

1. **Operator one-click (fastest, recommended).** In the operator's normal
   browser (already authenticated, stable VPN): Neon Console → VacancyRadar
   project → Settings → Logical Replication → Enable (irreversible
   `wal_level=logical`, restarts computes). Then dispatch
   `cdc-production-capture.yml`. Everything after the toggle is already
   automated and needs no Console.

2. **Neon API key — the full API path is CONFIRMED (verified 2026-06-05).**
   The original "verify first whether the API exposes the toggle" caveat is
   resolved: it does, end to end. Register a Neon **API key** (Console →
   Account settings → API keys → Create), store it in `D:\TXT\NEON.txt`, then
   from any non-RU egress (e.g. a US GitHub Actions runner — no VPN/geo
   dependency):

   ```bash
   # 1. find the VacancyRadar project_id (no Console needed once the key exists)
   curl -s -H "Authorization: Bearer $NEON_API_KEY" \
     https://console.neon.tech/api/v2/projects | jq '.projects[] | {id,name}'
   # 2. flip the toggle — IRREVERSIBLE wal_level=logical + restarts all computes
   curl -X PATCH "https://console.neon.tech/api/v2/projects/$PROJECT_ID" \
     -H "Authorization: Bearer $NEON_API_KEY" -H 'Content-Type: application/json' \
     -d '{"project":{"settings":{"enable_logical_replication":true}}}'
   ```

   Then dispatch `cdc-production-capture.yml` — zero Console interaction after
   the flip. **Correction to the original note:** the API base is
   `console.neon.tech/api/v2`, NOT `api.neon.tech` (the latter does not resolve
   — it was an error here). The ONLY remaining manual step is creating the API
   key, which needs exactly one authenticated Console session: there is no
   stored Neon account password and no live Neon/Google session cookie in any
   local browser profile (rechecked 2026-06-05), and autonomous Google/Neon
   browser login is the environment-blocked path described above. Once the key
   is in `D:\TXT\NEON.txt`, the whole enable + capture is one unattended run.

3. **Registration of a dedicated CDC source (fallback, lower fidelity).** If
   touching the live VacancyRadar project is undesirable, register a fresh
   Neon project (free tier) seeded from an anonymized `public.vacancies`
   export, enable Logical Replication there, and run the same capture against
   it. This proves the end-to-end CDC path on a real managed Postgres, but is
   explicitly a dedicated test source, not the production VacancyRadar DB —
   label it as such in the evidence and do not claim production capture.

4. **Stable egress for autonomous browser login.** If the CDP/iMac path is
   retried, first secure a stable non-RU channel (a paid/stable VPN node or a
   non-RU VPS as an SSH egress) so the multi-step Google login + 2FA can run
   for ~90 s without a drop; the login + 2FA script is otherwise proven.

Everything except the Console toggle is committed and pickup-ready:
`scripts/capture_production_cdc.sh`, `.github/workflows/cdc-production-capture.yml`,
the four `CDC_NEON_*` Actions secrets, and `tests/unit/test_cdc_production_capture_workflow.py`.

Production CDC onboarding is not approved yet. This runbook defines the
decision record and preflight checks required before attaching real Postgres or
MySQL sources to AgentFlow.

Do not create production connectors until every required input below is filled
and approved by the source-system owner, platform owner, and security owner.

## Current decision handoff

Status as of 2026-05-04: blocked on external production-source decisions.

The checked-in CDC path covers local/demo and Kubernetes-shaped staging
primitives only. The production decision record is still missing:

- Source owner and escalation contact.
- Secret owner for CDC user creation, rotation, and revocation.
- Source engine, hostname, port, database name, and approved table scope.
- Private network path from Kafka Connect to the source database.
- Existing Kubernetes Secret name and owner.
- Monitoring owner for connector lag, failures, and dead letters.
- Rollback owner authorized to pause or delete the connector.

Access triage on 2026-05-04 found no approved production-source inputs in the
repo or task prompt. `kubectl` is present through Docker Desktop tooling, but
there is no approved production context, source hostname, private network path,
existing Kubernetes Secret, monitoring owner, or rollback owner to inspect.
No production connector was created, paused, deleted, or queried.

Next operator packet to unblock review:

- Completed source-owner, secret-owner, platform-owner, and security-owner
  approval record.
- Source engine/version, hostname/port, database name, explicit table allowlist,
  data classification, and snapshot policy.
- Private network path proof and existing Kubernetes Secret name/namespace; do
  not include credential values.
- Monitoring owner, rollback owner, first-run connector status, topic list,
  redacted normalized event, and lag/dead-letter evidence.

Until those values are supplied and approved outside the repo, keep production
CDC disabled and treat this runbook as an operator handoff only.

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
