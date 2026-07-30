# Golden Operator acceptance — 2026-07-30

**Date:** 2026-07-30

**Exact commit:** `36ed1ecc250ac6c82ccc6f27de1b76a301b17a41`

**Audience:** ops / developers recording live verification evidence

**Result:** **PASS** (Operator + Helm golden-topology deployment only)

## Goal and boundary

Prove that a **clean checkout** of exact HEAD `36ed1ec` deploys on kind through
the Flink Kubernetes Operator and Helm chart, reaches a stable Flink job, and
holds that stability for a measured window with growing checkpoints and zero
leadership flaps.

### In scope

- Isolated clean checkout at exact HEAD `36ed1ecc250ac6c82ccc6f27de1b76a301b17a41`
- Clean-checkout API and Flink images built from that commit
- Flink Kubernetes Operator chart/app install
- Helm `agentflow` deploy with hooks enabled
- ServiceAccount preservation across Helm upgrade
- Flink CR / job RUNNING with checkpoints growing
- RBAC rendered/live rules and `kubectl auth can-i` for the job ServiceAccount
- Measured hold with no leader transitions and no JobManager leadership loss
- Kafka / API / Redis readiness observations on the acceptance stand

### Non-goals (not claimed)

- live Iceberg materialization from `events.validated`
- Kafka → PyFlink → Iceberg → ClickHouse → API production E2E
- checkpoint restore / replay without duplicate `(tenant_id, event_id)` rows
- fresh 4 h soak and backup/rollback rehearsal on the golden topology
- external penetration test
- production acceptance (`production.status` remains `candidate`)

## Baseline / environment

| Item | Value |
|------|-------|
| Route | local Grok CLI, profile `Grokw`, remote host `deproject-mac` |
| Cluster | `agentflow-golden-36ed1ec` |
| Context | `kind-agentflow-golden-36ed1ec` |
| Exact clean clone | `/tmp/agentflow-acceptance-36ed1ec-grokw-final` |
| Clone / local HEAD | `36ed1ecc250ac6c82ccc6f27de1b76a301b17a41` |
| Flink Kubernetes Operator chart/app | `1.15.0` |
| Operator image | `ghcr.io/apache/flink-kubernetes-operator:79d730b` |
| CRD patch | `flinkVersion` enum contains `v2_3` (verified) |
| Helm release | `agentflow` revision `1 -> 2`, deployed, hooks enabled |

## Operator and Helm evidence

| Item | Value |
|------|-------|
| ServiceAccount UID (preserved) | `a8f4ebd8-53de-4680-b89d-83d0114db852` |
| ServiceAccount creationTimestamp (preserved) | `2026-07-30T16:29:46Z` |
| Flink CR | `agentflow-stream-processor` |
| Flink CR UID | `0622bd9c-3cec-410c-b778-78440a3c0ba9` |
| Flink job ID | `0171cd969b5b300199c83dca620bd620` |
| Final hold state | `RUNNING / STABLE / READY / DEPLOYED` |
| JobManager / TaskManager | Ready; restart counts `0` |
| RBAC | rendered/live rules verified for `deployments`, `deployments/finalizers`, and `events` |
| `kubectl auth can-i` | `yes` for required deployment / finalizer / event / configmap operations as the `agentflow` ServiceAccount |
| Leader transitions | stayed `0 -> 0` |
| JobManager `lost leadership` | stayed `0` |

## Stability hold

| Item | Value |
|------|-------|
| Hold window | `2026-07-30T16:54:21Z` through `2026-07-30T17:04:46Z` |
| Duration | `10m25s` |
| Poll cadence | at most 40 seconds |
| Completed checkpoints | grew `2 -> 23` |
| Latest checkpoint ID | `2 -> 23` |
| Failed checkpoints | `0` |
| Mac NTP | healthy, approximately `-0.011 s -> -0.013 s`; absolute offset `< 0.5 s` |

## Supporting stand observations (not full E2E)

These confirm the acceptance stand stayed healthy during the Operator hold.
They do **not** close lake-to-serving E2E or Iceberg materialization.

| Component | Observation |
|-----------|-------------|
| Kafka Deployment | Ready `1/1`, pod restarts `0` |
| Kafka service ports | `9092` / `29093` |
| Required topics present | `orders.raw`, `events.validated`, `events.deadletter` |
| API | Ready, restarts `0` |
| Redis | Ready, restarts `0` |

## Acceptance-scaffold Kafka (historical + reproducibility)

The preliminary reviewed Kafka manifest was **not self-sufficient** in kind.
The Operator acceptance hold itself used two evidence-backed **live runtime
fixes** on the stand (historical fact):

1. `spec.template.spec.enableServiceLinks: false`
2. `KAFKA_CONTROLLER_QUORUM_VOTERS=1@127.0.0.1:29093`
   (plus an explicit inter-broker listener and widened startup/readiness probe
   windows)

That **reproducibility debt is now closed** by the tracked acceptance scaffold
`k8s/acceptance/kafka-kraft.yaml` and its unit contract
`tests/unit/test_kind_kafka_acceptance_scaffold.py`. The scaffold is
acceptance/staging only: it does **not** elevate production status and does
**not** prove production Kafka. Do **not** treat untracked `.grok-prompts`
manifests as product source of truth.

## Post-conditions

- Live cluster intentionally left running after the PASS hold
- No production-status elevation (`candidate` retained)
- No claim of Iceberg materialization, restore/replay, soak, or external gates

## Limits and next gates

This report closes only **clean kind + Flink Kubernetes Operator + Helm
deployment of the verified Flink OCI image** on exact HEAD `36ed1ec`, including
the measured stability hold.

Still pending for golden-topology production acceptance:

1. live Iceberg materialization from `events.validated`
2. Kafka → PyFlink → Iceberg → ClickHouse → API smoke
3. checkpoint restore and replay without duplicate `(tenant_id, event_id)` rows
4. fresh 4 h soak and rollback rehearsal on the golden topology
5. external penetration test
6. GitHub Environment `npm` approval-protection evidence

**Next atomic gate:** live Iceberg / lake-to-serving E2E on the accepted
Operator topology (or an independently authorized acceptance item from the
remaining list). Do not raise `production.status` above `candidate`.
