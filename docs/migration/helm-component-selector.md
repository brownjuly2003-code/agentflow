# Helm migration: API Deployment selector now carries `component: api` unconditionally

## Applies to

Operators upgrading an **existing** AgentFlow Helm release that was installed
with a chart **before** this one, where `worker.enabled=false` (the default).
Fresh installs and releases already running `worker.enabled=true` are **not**
affected.

## What changed and why

The API Deployment (`templates/deployment.yaml`) now adds
`app.kubernetes.io/component: api` to its pod template labels **and** its
`spec.selector.matchLabels` **unconditionally**. Previously that label was added
only when `worker.enabled=true`.

This fixes two audit findings:

- **#7 — immutable selector toggle-break.** `spec.selector` is immutable in
  Kubernetes. When the label was gated on `worker.enabled`, flipping that value
  on a live release changed the selector, so `helm upgrade` aborted with
  `spec.selector is immutable`. Making the label unconditional keeps the selector
  **constant** across the `worker.enabled` toggle, so the split can be enabled or
  disabled in place.
- **#6 — component-scoped PodDisruptionBudget.** The PDB now selects
  `component: api`, guaranteeing at least one *API* pod survives a voluntary
  disruption. That guarantee only holds if API pods **always** carry the label,
  which is why the pod-template label had to become unconditional too.

It also keeps API and worker pods in disjoint selector sets, so the two
Deployments can never adopt each other's pods.

## The one-time breaking upgrade

Because `spec.selector` is immutable, the **first** upgrade of a pre-existing
`worker.enabled=false` release onto this chart changes the selector from
`{name, instance}` to `{name, instance, component=api}`. The API server rejects
the in-place change:

```
Deployment.apps "<release>-agentflow" is invalid: spec.selector: Invalid value:
v1.LabelSelector{...}: field is immutable
```

`helm upgrade` fails and rolls back; nothing is left half-applied. Recreate the
API Deployment **once** to move past it. This is a one-time step — subsequent
upgrades are normal.

### Option A — zero-downtime (recommended for multi-replica / production)

Orphan the existing pods so they keep serving, let the recreated Deployment
stand up new pods, then reap the orphans:

```bash
kubectl delete deployment <release>-agentflow -n <namespace> --cascade=orphan
helm upgrade <release> <chart> [same flags as before]
# wait for the new (component=api) pods to become Ready, then remove the
# orphaned old pods — they lack component=api so the new Deployment won't adopt
# them and they will not be cleaned up automatically:
kubectl get pods -n <namespace> -l app.kubernetes.io/name=agentflow \
  -L app.kubernetes.io/component
kubectl delete pod <old-pod-names> -n <namespace>
```

### Option B — simplest (brief serving gap)

For a single-replica default install where a short gap is acceptable:

```bash
kubectl delete deployment <release>-agentflow -n <namespace>
helm upgrade <release> <chart> [same flags as before]
```

## Notes

- The chart does **not** ship a `pre-upgrade` hook to automate the delete. A hook
  that deletes the primary API Deployment would fire on **every** upgrade (helm
  hooks are not conditional on "did the selector change"), turning a one-time
  migration into a recurring outage. The manual step above runs exactly once, by
  operator decision.
- The Service selector is unaffected (Service selectors are mutable): it already
  narrows to `component: api` when `worker.enabled=true` and otherwise selects on
  `{name, instance}`, which still matches the API pods.
- Related NetworkPolicy change in the same release: a PostgreSQL `:5432` egress
  rule is now rendered when `controlPlane.store=postgres`. No migration action —
  it only adds an allowed egress.
