# Helm Deployment

## Overview

The AgentFlow Helm chart deploys the FastAPI API to Kubernetes with:

- a rolling-update `Deployment`
- a `Service` on port `8000`
- a `PersistentVolumeClaim` for DuckDB files
- a `HorizontalPodAutoscaler` driven by CPU
- optional `Ingress` with TLS
- mounted config files for tenants, SLOs, PII masking, API versioning, and security policy
- mounted secrets for the admin key and API-key config, either rendered by the
  chart or supplied through an existing Kubernetes Secret

The chart lives in `helm/agentflow`.

## Prerequisites

- Kubernetes 1.27+
- Helm 3.x
- metrics-server if you want the CPU-based HPA to scale automatically
- A container image for the API, published or loaded into the target cluster
- Storage class support if `persistence.enabled=true`

The chart deploys the API only. Redis, Kafka, Prometheus, Grafana, Jaeger, and other supporting services stay external to this chart.

## Prepare an image

The default chart values expect an image named `agentflow/api:1.1.0`.

If you are using Minikube, build or load an image before the install:

```bash
minikube image load agentflow/api:1.1.0
```

If your CI publishes a different image, override `image.repository` and `image.tag`.

## Install

Use a dedicated values file for production secrets and tenant configuration:

```yaml
# values-prod.yaml
image:
  repository: registry.example.com/agentflow/api
  tag: "1.1.0"

secrets:
  create: false
  existingSecret: agentflow-api-runtime-secret

config:
  tenants:
    tenants:
      - id: acme-corp
        display_name: "Acme Corp"
        kafka_topic_prefix: "acme"
        duckdb_schema: "acme"
        max_events_per_day: 1000000
        max_api_keys: 10
        allowed_entity_types: null
```

The existing Secret must contain `admin-key` and `api_keys.yaml`.
`api_keys.yaml` must use the same structured shape as `config/api_keys.yaml`.

Install the release:

```bash
helm install agentflow ./helm/agentflow -f values-prod.yaml
```

Quick dev install with only the admin key overridden, intentionally leaving API
keys empty until you mount or render `api_keys.yaml`:

```bash
helm install agentflow ./helm/agentflow --set secrets.adminKey=local-admin-key
```

## Verify rollout

Check the release status:

```bash
kubectl get pods -l app.kubernetes.io/instance=agentflow
kubectl rollout status deployment/agentflow
kubectl get hpa,pvc
```

Port-forward the service and call the health endpoint:

```bash
kubectl port-forward svc/agentflow 8000:8000
curl http://127.0.0.1:8000/v1/health
```

If `ingress.enabled=true`, verify the configured host instead of using port-forwarding.

## Configuration notes

- `config.duckdbPath` and `config.usageDbPath` should point to the mounted PVC path.
- `config.contractsDir` points at contract YAML files bundled into the image. The chart does not mount `config/contracts/` separately.
- `secrets.apiKeys.keys[*].key_id` is required for deterministic admin rotation and staging checks.
- Default `secrets.apiKeys.keys` is empty. Supply API-key config through `secrets.existingSecret` or through an environment-specific values file; do not reuse repository defaults as runtime credentials.
- If `secrets.create=false`, `secrets.existingSecret` must name a Kubernetes Secret with `admin-key` and `api_keys.yaml`.
- `config.tenants` is the source of truth for tenant routing and API version pinning.
- `autoscaling.enabled=true` creates an HPA from `minReplicas` to `maxReplicas`, but persistent DuckDB storage is guarded to one writer replica. Rendering fails when `persistence.enabled=true` and the chart is configured for more than one API writer replica.
- `ingress.tls` accepts the standard Helm ingress TLS structure.
- ConfigMap and Secret checksums are injected into the pod template, so `helm upgrade` rolls the deployment when mounted config changes.
- DuckDB is still a stateful local file. If your storage class only supports `ReadWriteOnce`, start with `replicaCount: 1` until you validate your storage and concurrency model.
- Optional DuckDB file encryption is runtime-configured with `AGENTFLOW_DUCKDB_ENCRYPTION_KEY` or `AGENTFLOW_DUCKDB_ENCRYPTION_KEY_FILE`; use `extraEnv` with a `secretKeyRef` to supply the key. The default remains unencrypted for backward compatibility.
- DuckDB encryption is a local at-rest hardening option only. It is not a NIST, GDPR, HIPAA, SOC 2, or external-compliance attestation by itself.
- Optional append-only audit export is runtime-configured with `AGENTFLOW_AUDIT_LOG_PATH`, which writes a hash-chained JSONL file in addition to DuckDB usage analytics. For externally immutable retention, operators still need object-lock or SIEM evidence outside this chart.

## Contract Maintenance

- `helm/agentflow/values.schema.json` is the chart contract for runtime values consumed from Helm.
- If you add, rename, or make required a field under `config.tenants` or `secrets.apiKeys`, update the schema, chart defaults, and environment-specific values together.
- Keep the mounted file shape in `templates/configmap.yaml` and `templates/secret.yaml` aligned with the runtime Pydantic models in `src/ingestion/tenant_router.py` and `src/serving/api/auth/manager.py`.
- Validate contract changes with `helm lint helm/agentflow -f k8s/staging/values-staging.yaml` before staging rehearsal.

## Upgrade

Update the values file or image tag, then run:

```bash
helm upgrade agentflow ./helm/agentflow -f values-prod.yaml
kubectl rollout status deployment/agentflow
```

The deployment strategy uses `maxUnavailable: 0` and `maxSurge: 1` to avoid downtime during a normal rolling update.

## Uninstall

Remove the release:

```bash
helm uninstall agentflow
```

If you also want to remove persisted DuckDB data, delete the PVC after the uninstall:

```bash
kubectl delete pvc agentflow
```

## Troubleshooting

- `ImagePullBackOff`: set `image.repository` and `image.tag` to a reachable image or load the image into Minikube.
- `Pending` pod with PVC errors: choose a valid `persistence.storageClassName` or disable persistence for ephemeral environments.
- `503` on admin endpoints: set `secrets.adminKey`.
- Missing auth or tenant config: check the rendered `api_keys.yaml` and `tenants.yaml` values inside the mounted Secret and ConfigMap.
