# Helm Deployment

## Overview

The AgentFlow Helm chart deploys the FastAPI API to Kubernetes with:

- a rolling-update `Deployment`
- a `Service` on port `8000`
- a `PersistentVolumeClaim` for DuckDB files
- a `HorizontalPodAutoscaler` driven by CPU
- optional `Ingress` with TLS
- mounted config files for tenants, SLOs, PII masking, API versioning, and security policy
- mounted secrets for the admin key and bcrypt-hashed API keys

The chart lives in `helm/agentflow`.

## Prerequisites

- Kubernetes 1.27+
- Helm 3.x
- metrics-server if you want the CPU-based HPA to scale automatically
- A container image for the API, published or loaded into the target cluster
- Storage class support if `persistence.enabled=true`

The chart deploys the API only. Redis, Kafka, Prometheus, Grafana, Jaeger, and other supporting services stay external to this chart.

## Prepare an image

The default chart values expect an image named `agentflow/api:1.0.0`.

If you are using Minikube, build or load an image before the install:

```bash
minikube image load agentflow/api:1.0.0
```

If your CI publishes a different image, override `image.repository` and `image.tag`.

## Install

Use a dedicated values file for production secrets and tenant configuration:

```yaml
# values-prod.yaml
image:
  repository: registry.example.com/agentflow/api
  tag: "1.0.0"

secrets:
  adminKey: "replace-me"
  apiKeys: |
    keys:
      - key_hash: "$2b$12$..."
        name: "Support Agent"
        tenant: "acme-corp"
        rate_limit_rpm: 60
        allowed_entity_types: null
        created_at: "2026-04-11"

config:
  tenants: |
    tenants:
      - id: acme-corp
        display_name: "Acme Corp"
        kafka_topic_prefix: "acme"
        duckdb_schema: "acme"
        max_events_per_day: 1000000
        max_api_keys: 10
        allowed_entity_types: null
```

Install the release:

```bash
helm install agentflow ./helm/agentflow -f values-prod.yaml
```

Quick dev install with only the admin key overridden:

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
- `secrets.apiKeys` must contain bcrypt hashes, not plaintext API keys.
- `config.tenants` is the source of truth for tenant routing and API version pinning.
- `autoscaling.enabled=true` creates an HPA from `minReplicas` to `maxReplicas`.
- `ingress.tls` accepts the standard Helm ingress TLS structure.
- ConfigMap and Secret checksums are injected into the pod template, so `helm upgrade` rolls the deployment when mounted config changes.
- DuckDB is still a stateful local file. If your storage class only supports `ReadWriteOnce`, start with `replicaCount: 1` until you validate your storage and concurrency model.

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
