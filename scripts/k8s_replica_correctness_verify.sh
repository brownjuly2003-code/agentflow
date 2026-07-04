#!/usr/bin/env bash
#
# ADR 0010 rollout slice 6 / cutover plan Phase 3 — replica-correctness verify.
#
# Runs against an ALREADY-DEPLOYED scale-profile cluster (replicaCount>=2,
# controlPlane.store=postgres, serving.backend=clickhouse). Bring it up with:
#
#   helm upgrade --install agentflow helm/agentflow \
#     -f k8s/staging/values-staging.yaml \
#     -f k8s/staging/values-staging-scale.yaml \
#     --namespace agentflow --wait
#
# after standing up in-cluster PostgreSQL + ClickHouse + Redis and their
# secrets (agentflow-controlplane-pg / agentflow-clickhouse).
#
# What this script automates (deterministic over the HTTP API):
#   [Check 1] the deployment actually runs >=2 ready pods behind one Service,
#             and the control-plane store env is 'postgres' on every pod;
#   [Check 2] cross-pod registration visibility — a webhook registered through
#             the Service is visible on repeated reads that round-robin the
#             pods. This is the SHARPEST split-brain (ADR 0010 §Verified state
#             inventory class 5): on the embedded YAML store it fails (pod A's
#             registration is invisible on pod B); on postgres it holds.
#
# What it does NOT automate (documented recipe — see
# docs/clickhouse-cutover-plan.md Phase 3):
#   - exactly-one delivery per (webhook, event) across two pods, and
#   - one alert page per incident.
#   Both need an emitted pipeline event / alert-triggering tick plus a capture
#   sink. The STORE-level guarantee behind them (idempotent enqueue insert-win,
#   single-flight alert claim, outbox<->dead-letter atomicity) is already
#   live-verified by the slice-5 standalone-PG probe suite (31/31,
#   docs/perf/control-plane-pg-verify-2026-07-03.md); Phase 3 only adds the
#   two-real-pods topology proof on top.
#
# NOTE: authored on a Docker-less host and not yet executed end-to-end — it is
# the Mac/CI half of E4 (kind + Docker required). Syntax-checked (bash -n) only.
set -Eeuo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
NAMESPACE="${NAMESPACE:-agentflow}"
RELEASE_NAME="${RELEASE_NAME:-agentflow}"
# A support-tenant key with webhook scope (matches k8s_smoke_test.sh defaults /
# values-staging.yaml fixtures).
API_KEY="${API_KEY:-af-prod-agent-ops-def456}"
MIN_REPLICAS="${MIN_REPLICAS:-2}"
# A public https URL that passes the egress guard but is never actually called
# (no matching event is emitted in this check).
WEBHOOK_URL="${WEBHOOK_URL:-https://example.com/agentflow-replica-verify}"
LIST_READS="${LIST_READS:-8}"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# --- Check 1: >=2 ready pods, all on the postgres control-plane store ---------
echo "==> [Check 1] deployment runs >=${MIN_REPLICAS} ready pods on postgres store"
kubectl wait --namespace "$NAMESPACE" --for=condition=available \
  "deployment/$RELEASE_NAME" --timeout=180s

ready=$(kubectl get deployment "$RELEASE_NAME" --namespace "$NAMESPACE" \
  -o jsonpath='{.status.readyReplicas}')
ready="${ready:-0}"
(( ready >= MIN_REPLICAS )) || fail "only ${ready} ready replica(s), need >= ${MIN_REPLICAS}"

mapfile -t pods < <(kubectl get pods --namespace "$NAMESPACE" \
  -l "app.kubernetes.io/instance=$RELEASE_NAME" -o name)
(( ${#pods[@]} >= MIN_REPLICAS )) || fail "only ${#pods[@]} pod(s) found"

for pod in "${pods[@]}"; do
  store=$(kubectl get "$pod" --namespace "$NAMESPACE" \
    -o jsonpath='{.spec.containers[0].env[?(@.name=="AGENTFLOW_CONTROLPLANE_STORE")].value}')
  [[ "$store" == "postgres" ]] || fail "$pod has AGENTFLOW_CONTROLPLANE_STORE=${store:-<unset>}, expected postgres"
done
pass "${ready} ready pods, all AGENTFLOW_CONTROLPLANE_STORE=postgres"

# --- Check 2: cross-pod registration visibility -------------------------------
echo "==> [Check 2] webhook registered via the Service is visible from every pod"
reg=$(curl -fsS -X POST \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"url\":\"$WEBHOOK_URL\"}" \
  "$BASE_URL/v1/webhooks")
webhook_id=$(printf '%s' "$reg" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
[[ -n "$webhook_id" ]] || fail "registration returned no id: $reg"
echo "    registered webhook_id=$webhook_id"

cleanup() {
  curl -fsS -X DELETE -H "X-API-Key: $API_KEY" \
    "$BASE_URL/v1/webhooks/$webhook_id" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Round-robin the Service; on the embedded store a read served by the pod that
# did NOT register would miss the id. Postgres shares one registration table,
# so every read must see it.
misses=0
for i in $(seq 1 "$LIST_READS"); do
  listing=$(curl -fsS -H "X-API-Key: $API_KEY" "$BASE_URL/v1/webhooks")
  if ! printf '%s' "$listing" | grep -q "$webhook_id"; then
    misses=$((misses + 1))
    echo "    read #$i did NOT see $webhook_id"
  fi
done
(( misses == 0 )) || fail "webhook invisible on ${misses}/${LIST_READS} reads — split-brain (embedded store?)"
pass "webhook visible on all ${LIST_READS} round-robin reads across pods"

echo "==> replica-correctness verify OK (Checks 1-2 automated; see cutover plan Phase 3 for the delivery/alert recipe)"
