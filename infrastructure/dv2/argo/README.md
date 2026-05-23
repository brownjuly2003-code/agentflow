# DV2.0 Argo Workflows Orchestration

Replaces the standalone cold-offload CronJobs with a coordinated DAG:
validate hubs before links, links before satellites, fan out cold-offload
across all five branches in parallel, then verify mirrors against
source satellites. The Workflow that you submit re-uses the same
`clickhouse-server:25.5` container image as the existing CronJobs — the
only thing that's new is the orchestration substrate.

## Why Argo here (and not just CronJobs)

The five cold-offload CronJobs in `cold-offload-fanout.yaml` run on
independent schedules with no cross-job coordination. That's fine for
the baseline demo, but production DV2.0 needs:

1. **Layer ordering** — offload can't run until satellites are at rest;
   satellites can't be at rest until links are populated; links assume
   hubs exist. Argo's DAG dependencies encode that directly.
2. **Fan-out + barrier** — five parallel branches, then a single
   verification step that only fires when all five mirrors are written.
   `withParam` + `dependencies: [cold-offload]` is the standard idiom.
3. **One observability surface** — a single Workflow object on the
   cluster shows the entire run's health, not 5 sibling CronJob
   histories that someone has to cross-reference.
4. **Retry semantics** — `retryStrategy` (not used here yet, easy to
   add) lets cold-offload retry once on transient S3 failures without
   re-running the upstream validation steps.

## Install

```bash
bash infrastructure/dv2/argo/install.sh
```

This is idempotent — re-runs only patch deltas.

## Submit a run

```bash
kubectl create -n dv2 -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: dv2-refresh-
spec:
  workflowTemplateRef:
    name: dv2-refresh
EOF
```

Status:

```bash
kubectl get workflow -n dv2 -o wide
kubectl get workflow -n dv2 <name> -o jsonpath='{.status.phase}'
kubectl logs -n dv2 <name>-<step-pod> -c main
```

## DAG layout

```
promote-oltp
    │
validate-hubs
    │
    ├── validate-links
    │       │
    │       └─────────────┐
    └── validate-satellites
                          │
              cold-offload (fan-out: msk, spb, ekb, dxb, ala)
                          │
                  verify-mirrors
```

Step contracts:

| Step                 | Asserts                                                            |
| -------------------- | ------------------------------------------------------------------ |
| `promote-oltp`       | Re-promotes Postgres OLTP rows into `rv.hub_customer` (idempotent) |
| `validate-hubs`      | All 4 hubs non-empty + `_hk` unique per hub                        |
| `validate-links`     | Zero orphan `lnk_order_customer` rows vs `hub_order`               |
| `validate-satellites`| `sat_order_pricing__1c__msk` non-empty + branch distribution OK    |
| `cold-offload-*`     | Writes `customers_anon.parquet` to MinIO + verifies read-back > 0  |
| `verify-mirrors`     | Source-satellite row count == mirror row count for all 5 branches  |

## RBAC model

`rbac.yaml` creates ServiceAccount `dv2-argo-runner` in `dv2` with a
narrowly-scoped Role:

- `workflowtaskresults`: create / patch / get (Argo emissary needs this)
- `pods`, `pods/log`: get / list / watch
- `pods/exec`: create

Workflow templates explicitly bind to `dv2-argo-runner` (not `default`),
so elevated executor permissions don't bleed into other workloads in
the namespace.

## Production swap

Identical to the CronJob path. Replace the `minio-creds` Secret with a
cloud-provider credential Secret and change `S3_ENDPOINT` to the real
object-store URL. The WorkflowTemplate isn't touched.

Add `retryStrategy: {limit: 2, retryPolicy: OnError}` to
`cold-offload-branch` if production S3 has measured intermittent
failures — Argo handles the back-off and per-step state automatically.
