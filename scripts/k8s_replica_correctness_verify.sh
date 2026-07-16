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
# What this script automates (deterministic over the HTTP API + CH insert):
#   [Check 1] the deployment actually runs >=2 ready pods behind one Service,
#             and the control-plane store env is 'postgres' on every pod;
#   [Check 2] cross-pod registration visibility — a webhook registered through
#             the Service is visible on repeated reads that round-robin the
#             pods. This is the SHARPEST split-brain (ADR 0010 §Verified state
#             inventory class 5): on the embedded YAML store it fails (pod A's
#             registration is invisible on pod B); on postgres it holds.
#   [Check 3] exactly-one delivery per (webhook, event) — insert one journal
#             row into the shared ClickHouse pipeline_events table, wait for
#             both pods' scanners to race the durable enqueue, then assert
#             GET /v1/webhooks/{id}/logs shows exactly one delivery_id for
#             that event_id (insert-win: only the enqueue winner POSTs).
#
# What it does NOT automate (documented recipe — see
# docs/clickhouse-cutover-plan.md Phase 3):
#   - one alert page per incident (needs a triggering evaluation window +
#     capture of alert_history). The store-level single-flight claim is already
#     live-verified by the slice-5 PG probe suite
#     (docs/perf/control-plane-pg-verify-2026-07-03.md).
#
# Live topology proof (Checks 1-2): docs/perf/e4-replica-topology-2026-07-11.md
# (kind on deproject-mac). Check 3 is automated here; re-run on the same stand
# to close the remaining delivery-topology STATUS item.
set -Eeuo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
NAMESPACE="${NAMESPACE:-agentflow}"
RELEASE_NAME="${RELEASE_NAME:-agentflow}"
# A support-tenant key with webhook scope (matches k8s_smoke_test.sh defaults /
# values-staging.yaml fixtures).
API_KEY="${API_KEY:-af-prod-agent-ops-def456}"
MIN_REPLICAS="${MIN_REPLICAS:-2}"
# Public https URL that passes the egress guard. example.com returns 2xx so the
# inline delivery marks the queue row delivered (no redrive noise in the logs).
WEBHOOK_URL="${WEBHOOK_URL:-https://example.com/agentflow-replica-verify}"
LIST_READS="${LIST_READS:-8}"

# Check 3 — ClickHouse journal insert (shared serving store both pods scan).
CLICKHOUSE_DATABASE="${CLICKHOUSE_DATABASE:-agentflow}"
CLICKHOUSE_USER="${CLICKHOUSE_USER:-default}"
CLICKHOUSE_SECRET="${CLICKHOUSE_SECRET:-agentflow-clickhouse}"
CLICKHOUSE_PASSWORD_KEY="${CLICKHOUSE_PASSWORD_KEY:-clickhouse-password}"
# Pod/resource name. Empty → auto-detect first pod matching the label/name.
CLICKHOUSE_POD="${CLICKHOUSE_POD:-}"
DELIVERY_WAIT_SECONDS="${DELIVERY_WAIT_SECONDS:-45}"
DELIVERY_POLL_SECONDS="${DELIVERY_POLL_SECONDS:-2}"
# Tenant of the inserted event — must match the API key's tenant (staging: default).
EVENT_TENANT="${EVENT_TENANT:-default}"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

webhook_id=""
cleanup() {
  if [[ -n "${webhook_id}" ]]; then
    curl -fsS -X DELETE -H "X-API-Key: $API_KEY" \
      "$BASE_URL/v1/webhooks/$webhook_id" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# --- Check 1: >=2 ready pods, all on the postgres control-plane store ---------
echo "==> [Check 1] deployment runs >=${MIN_REPLICAS} ready pods on postgres store"
kubectl wait --namespace "$NAMESPACE" --for=condition=available \
  "deployment/$RELEASE_NAME" --timeout=180s

ready=$(kubectl get deployment "$RELEASE_NAME" --namespace "$NAMESPACE" \
  -o jsonpath='{.status.readyReplicas}')
ready="${ready:-0}"
(( ready >= MIN_REPLICAS )) || fail "only ${ready} ready replica(s), need >= ${MIN_REPLICAS}"

# Bash 3.2 (macOS system bash) has no mapfile; build the array portably.
# Only Running API pods: the pre-install provision Job shares the same
# app.kubernetes.io/instance label but is Completed and has no control-plane env.
pods=()
while IFS= read -r line; do
  [[ -n "$line" ]] && pods+=("$line")
done < <(kubectl get pods --namespace "$NAMESPACE" \
  -l "app.kubernetes.io/instance=$RELEASE_NAME" \
  --field-selector=status.phase=Running -o name)
(( ${#pods[@]} >= MIN_REPLICAS )) || fail "only ${#pods[@]} Running pod(s) found"

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

# --- Check 3: exactly-one delivery per (webhook, event) -----------------------
echo "==> [Check 3] exactly-one delivery for one journal event scanned by both pods"

if [[ -z "$CLICKHOUSE_POD" ]]; then
  # Prefer a pod whose name contains clickhouse (e4 stand: agentflow-clickhouse-*).
  while IFS= read -r line; do
    [[ -n "$line" ]] && CLICKHOUSE_POD="${line#pod/}" && break
  done < <(kubectl get pods --namespace "$NAMESPACE" -o name | grep -i clickhouse || true)
fi
[[ -n "$CLICKHOUSE_POD" ]] || fail "no ClickHouse pod found in namespace $NAMESPACE (set CLICKHOUSE_POD=...)"

event_id="replica-e4-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:16])')"
echo "    clickhouse_pod=$CLICKHOUSE_POD event_id=$event_id tenant=$EVENT_TENANT"

# Password is optional (some stands use empty/default trust); never print it.
ch_pass=""
if kubectl get secret "$CLICKHOUSE_SECRET" --namespace "$NAMESPACE" >/dev/null 2>&1; then
  ch_pass=$(kubectl get secret "$CLICKHOUSE_SECRET" --namespace "$NAMESPACE" \
    -o "jsonpath={.data.${CLICKHOUSE_PASSWORD_KEY}}" | (base64 --decode 2>/dev/null || base64 -d 2>/dev/null || true))
fi

# processed_at = now() so the row sits after any scan cursor advanced over seed.
# Columns match ClickHouseBackend SERVING_TABLE_COLUMNS + tenant_id.
insert_sql="INSERT INTO ${CLICKHOUSE_DATABASE}.pipeline_events (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at) VALUES ('${event_id}', 'events.validated', '${EVENT_TENANT}', 'ORD-REPLICA-E4', 'order.created', 10, now())"

if [[ -n "$ch_pass" ]]; then
  kubectl exec --namespace "$NAMESPACE" "$CLICKHOUSE_POD" -- \
    clickhouse-client --user "$CLICKHOUSE_USER" --password "$ch_pass" --query "$insert_sql" \
    || fail "ClickHouse insert failed (pod=$CLICKHOUSE_POD user=$CLICKHOUSE_USER)"
else
  kubectl exec --namespace "$NAMESPACE" "$CLICKHOUSE_POD" -- \
    clickhouse-client --user "$CLICKHOUSE_USER" --query "$insert_sql" \
    || fail "ClickHouse insert failed (pod=$CLICKHOUSE_POD user=$CLICKHOUSE_USER, no password secret)"
fi
echo "    inserted pipeline_events row"

# Both pods poll ~2s; enqueue is insert-win on (webhook_id, event_id). Only the
# winner calls deliver() and writes webhook_deliveries rows for this event.
deadline=$(( $(date +%s) + DELIVERY_WAIT_SECONDS ))
unique_ids=0
log_count=0
while (( $(date +%s) < deadline )); do
  logs_json=$(curl -fsS -H "X-API-Key: $API_KEY" \
    "$BASE_URL/v1/webhooks/$webhook_id/logs")
  # Count distinct delivery_id for this event_id. Multiple attempt rows may share
  # one delivery_id (inline retries); two pods winning would produce two ids.
  counts=$(printf '%s' "$logs_json" | EVENT_ID="$event_id" python3 -c "
import json, os, sys
eid = os.environ['EVENT_ID']
logs = json.load(sys.stdin).get('logs') or []
matched = [l for l in logs if str(l.get('event_id') or '') == eid]
ids = {str(l.get('delivery_id') or '') for l in matched if l.get('delivery_id')}
ids.discard('')
print(len(ids), len(matched))
")
  # shellcheck disable=SC2086
  set -- $counts
  unique_ids=${1:-0}
  log_count=${2:-0}
  if (( unique_ids >= 1 )); then
    break
  fi
  sleep "$DELIVERY_POLL_SECONDS"
done

(( unique_ids >= 1 )) || fail "no delivery log for event_id=$event_id within ${DELIVERY_WAIT_SECONDS}s (scanners idle or CH not shared)"
(( unique_ids == 1 )) || fail "expected exactly 1 delivery_id for event_id=$event_id, got ${unique_ids} (split delivery across pods)"
pass "exactly one delivery_id for event_id=$event_id (${log_count} log row(s))"

echo "==> replica-correctness verify OK (Checks 1-3 automated; alert single-page remains a cutover-plan recipe)"
