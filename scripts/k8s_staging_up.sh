#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-agentflow-staging}"
NAMESPACE="${NAMESPACE:-agentflow}"
RELEASE_NAME="${RELEASE_NAME:-agentflow}"
IMAGE_TAG="${IMAGE_TAG:-staging}"
API_IMAGE="${API_IMAGE:-agentflow/api:${IMAGE_TAG}}"
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

echo "==> Building API image $API_IMAGE..."
docker build -t "$API_IMAGE" -f - "$ROOT_DIR" <<'EOF'
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY requirements.txt /app/requirements.txt
COPY src /app/src
COPY config /app/config
COPY contracts /app/contracts
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir bcrypt \
 && pip install --no-cache-dir -e . \
 && pip install --no-cache-dir pyiceberg
RUN cat > /app/host_loopback_proxy.py <<'PY'
import asyncio
import os
import signal


LISTEN_HOST = "127.0.0.1"
TARGET_HOST = os.environ["HOST_LOOPBACK_PROXY_TARGET"]
PORT_START = int(os.getenv("HOST_LOOPBACK_PROXY_RANGE_START", "32768"))
PORT_END = int(os.getenv("HOST_LOOPBACK_PROXY_RANGE_END", "65535"))


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _handle(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    port = client_writer.get_extra_info("sockname")[1]
    target_reader, target_writer = await asyncio.open_connection(TARGET_HOST, port)
    await asyncio.gather(
        _pipe(client_reader, target_writer),
        _pipe(target_reader, client_writer),
    )


async def _main() -> None:
    servers = []
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    for port in range(PORT_START, PORT_END + 1):
        servers.append(await asyncio.start_server(_handle, LISTEN_HOST, port))

    print(
        f"Host loopback relay listening on {LISTEN_HOST}:{PORT_START}-{PORT_END} -> {TARGET_HOST}",
        flush=True,
    )

    await stop.wait()

    for server in servers:
        server.close()
        await server.wait_closed()


asyncio.run(_main())
PY
EOF

echo "==> Loading image into kind..."
if ! kind load docker-image "$API_IMAGE" --name "$CLUSTER_NAME"; then
  echo "==> kind load timed out, falling back to ctr import..."
  docker save "$API_IMAGE" | docker exec -i "${CLUSTER_NAME}-control-plane" ctr --namespace=k8s.io images import -
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

echo "==> Installing Helm chart..."
helm upgrade --install "$RELEASE_NAME" "$ROOT_DIR/helm/agentflow" \
  -f "$ROOT_DIR/k8s/staging/values-staging.yaml" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --atomic \
  --wait \
  --timeout 5m \
  --debug

echo "==> Enabling host loopback relay for webhook callbacks..."
kubectl set env "deployment/$RELEASE_NAME" \
  --namespace "$NAMESPACE" \
  HOST_LOOPBACK_PROXY_TARGET="$HOST_LOOPBACK_PROXY_TARGET" \
  HOST_LOOPBACK_PROXY_RANGE_START="$HOST_LOOPBACK_PROXY_RANGE_START" \
  HOST_LOOPBACK_PROXY_RANGE_END="$HOST_LOOPBACK_PROXY_RANGE_END"

kubectl patch deployment "$RELEASE_NAME" \
  --namespace "$NAMESPACE" \
  --type=json \
  -p='[
    {"op":"replace","path":"/spec/template/spec/containers/0/command","value":["/bin/sh","-lc"]},
    {"op":"add","path":"/spec/template/spec/containers/0/args","value":["python /app/host_loopback_proxy.py >/tmp/host-loopback-proxy.log 2>&1 & exec uvicorn src.serving.api.main:app --host 0.0.0.0 --port 8000"]}
  ]'

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
