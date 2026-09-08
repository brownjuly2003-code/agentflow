#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-agentflow-staging}"
NAMESPACE="${NAMESPACE:-agentflow}"
RELEASE_NAME="${RELEASE_NAME:-agentflow}"
PROMOTION_VALUES_FILE="${PROMOTION_VALUES_FILE:-}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
HOST_GATEWAY_HELPER_IMAGE="${HOST_GATEWAY_HELPER_IMAGE:-alpine:3.20}"
HOST_LOOPBACK_PROXY_TARGET="${HOST_LOOPBACK_PROXY_TARGET:-}"
HOST_LOOPBACK_PROXY_RANGE_START="${HOST_LOOPBACK_PROXY_RANGE_START:-32768}"
HOST_LOOPBACK_PROXY_RANGE_END="${HOST_LOOPBACK_PROXY_RANGE_END:-65535}"

for cmd in bash curl docker helm kind kubectl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
done

cd "$ROOT_DIR"

if [[ -z "$PROMOTION_VALUES_FILE" ]]; then
  echo "A verified promotion values file is required via PROMOTION_VALUES_FILE." >&2
  exit 1
fi
if [[ -L "$PROMOTION_VALUES_FILE" || ! -f "$PROMOTION_VALUES_FILE" ]]; then
  echo "Promotion values file must be a regular file: $PROMOTION_VALUES_FILE" >&2
  exit 1
fi
PROMOTION_VALUES_FILE="$(cd "$(dirname "$PROMOTION_VALUES_FILE")" && pwd)/$(basename "$PROMOTION_VALUES_FILE")"

on_failure() {
  local exit_code=$?

  trap - ERR
  echo "==> FAILURE: collecting diagnostics (exit code: $exit_code)"
  helm history "$RELEASE_NAME" --namespace "$NAMESPACE" || true
  kubectl get all --all-namespaces || true
  kubectl describe deployment "$RELEASE_NAME" --namespace "$NAMESPACE" || true
  kubectl describe pod --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" || true
  for pod in $(kubectl get pods --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o name 2>/dev/null); do
    echo "--- logs $pod (current) ---"
    kubectl logs --namespace "$NAMESPACE" "$pod" --tail=200 || true
    echo "--- logs $pod (previous) ---"
    kubectl logs --namespace "$NAMESPACE" "$pod" --tail=200 -p || true
  done
  kubectl get events --namespace "$NAMESPACE" --sort-by='.lastTimestamp' | tail -50 || true
  exit "$exit_code"
}

trap on_failure ERR

resolve_host_gateway_ip() {
  if [[ -n "$HOST_LOOPBACK_PROXY_TARGET" ]]; then
    printf '%s\n' "$HOST_LOOPBACK_PROXY_TARGET"
    return 0
  fi

  docker run --rm \
    --add-host host.docker.internal:host-gateway \
    "$HOST_GATEWAY_HELPER_IMAGE" \
    sh -lc "getent hosts host.docker.internal | awk '/\\./ {print \$1; exit}'"
}

HOST_LOOPBACK_PROXY_TARGET="$(resolve_host_gateway_ip)"
if [[ -z "$HOST_LOOPBACK_PROXY_TARGET" ]]; then
  echo "Unable to resolve host gateway IP for webhook loopback relay." >&2
  exit 1
fi

if ! kind get clusters | grep -qx "$CLUSTER_NAME"; then
  echo "==> Creating kind cluster..."
  kind create cluster --name "$CLUSTER_NAME" --config "$ROOT_DIR/k8s/kind-config.yaml"
else
  echo "==> Reusing kind cluster $CLUSTER_NAME"
fi

kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE" >/dev/null

echo "==> Ensuring Redis is available for rate limiting..."
kubectl apply --namespace "$NAMESPACE" -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agentflow-redis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: agentflow-redis
  template:
    metadata:
      labels:
        app: agentflow-redis
    spec:
      containers:
        - name: redis
          image: redis:7.4-alpine
          ports:
            - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: agentflow-redis
spec:
  selector:
    app: agentflow-redis
  ports:
    - name: redis
      port: 6379
      targetPort: 6379
EOF

kubectl rollout status deployment/agentflow-redis --namespace "$NAMESPACE" --timeout=180s

echo "==> Installing verified promoted digest with Helm..."
helm upgrade --install "$RELEASE_NAME" "$ROOT_DIR/helm/agentflow" \
  -f "$ROOT_DIR/k8s/staging/values-staging.yaml" \
  -f "$PROMOTION_VALUES_FILE" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --atomic \
  --wait \
  --timeout 5m \
  --debug

echo "==> Enabling host loopback relay for webhook callbacks..."
# The relay listens on 127.0.0.1 inside the pod and forwards to the host
# gateway, so the E2E webhook callback URL is http://127.0.0.1:<port>/callback.
# The SSRF egress guard rejects 127.0.0.1 as loopback by default; allowlist
# exactly the relay loopback here (ephemeral staging only) so the webhook
# delivery test passes without weakening the guard for real targets.
# command/args that start the relay live in k8s/staging/values-staging.yaml
# (Helm desired state) so a later helm upgrade cannot orphan live-only args.
kubectl set env "deployment/$RELEASE_NAME" \
  --namespace "$NAMESPACE" \
  HOST_LOOPBACK_PROXY_TARGET="$HOST_LOOPBACK_PROXY_TARGET" \
  HOST_LOOPBACK_PROXY_RANGE_START="$HOST_LOOPBACK_PROXY_RANGE_START" \
  HOST_LOOPBACK_PROXY_RANGE_END="$HOST_LOOPBACK_PROXY_RANGE_END" \
  AGENTFLOW_EGRESS_ALLOWED_HOSTS="127.0.0.1"

echo "==> Patching service to fixed NodePort..."
kubectl patch service "$RELEASE_NAME" \
  --namespace "$NAMESPACE" \
  --type=json \
  -p='[{"op":"replace","path":"/spec/type","value":"NodePort"},{"op":"add","path":"/spec/ports/0/nodePort","value":30080}]'

echo "==> Waiting for deployment rollout..."
kubectl rollout status "deployment/$RELEASE_NAME" --namespace "$NAMESPACE" --timeout=180s

echo "==> Running smoke tests..."
BASE_URL="$BASE_URL" NAMESPACE="$NAMESPACE" RELEASE_NAME="$RELEASE_NAME" bash "$ROOT_DIR/scripts/k8s_smoke_test.sh"

echo "==> Staging ready at $BASE_URL"
