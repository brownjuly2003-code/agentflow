#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
NAMESPACE="${NAMESPACE:-agentflow}"
RELEASE_NAME="${RELEASE_NAME:-agentflow}"
SUPPORT_API_KEY="${SUPPORT_API_KEY:-af-prod-agent-support-abc123}"
OPS_API_KEY="${OPS_API_KEY:-af-prod-agent-ops-def456}"

cd "$ROOT_DIR"

kubectl wait \
  --namespace "$NAMESPACE" \
  --for=condition=available \
  "deployment/$RELEASE_NAME" \
  --timeout=180s

deadline=$((SECONDS + 180))
until curl -fsS "$BASE_URL/v1/health" >/tmp/agentflow-k8s-health.json 2>/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for $BASE_URL/v1/health" >&2
    exit 1
  fi
  sleep 2
done

grep -q '"status"' /tmp/agentflow-k8s-health.json

curl -fsS \
  -H "X-API-Key: $SUPPORT_API_KEY" \
  "$BASE_URL/v1/entity/order/ORD-20260404-1001" \
  >/tmp/agentflow-k8s-order.json

grep -q 'ORD-20260404-1001' /tmp/agentflow-k8s-order.json

curl -fsS \
  -H "X-API-Key: $OPS_API_KEY" \
  -H "Content-Type: application/json" \
  -X POST \
  -d '{"question":"Show me top 3 products"}' \
  "$BASE_URL/v1/query" \
  >/tmp/agentflow-k8s-query.json

grep -q '"sql"' /tmp/agentflow-k8s-query.json
