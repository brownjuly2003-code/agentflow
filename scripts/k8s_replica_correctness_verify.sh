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
#   [Check 4] one alert page per incident — create a rule that fires on the
#             shared metric store; both pods' alert dispatchers race
#             claim_alert_tick; assert GET /v1/alerts/{id}/history has exactly
#             one successful alert.triggered delivery (not one per pod).
#
# Store-level single-flight claim is also live-verified by the slice-5 PG probe
# suite (docs/perf/control-plane-pg-verify-2026-07-03.md). This script adds the
# two-real-pods emission layer on top.
#
# Live topology proof (Checks 1-2): docs/perf/e4-replica-topology-2026-07-11.md
# (kind on deproject-mac). Check 3 live: docs/perf/e4-check3-exactly-one-delivery-2026-07-16.md.
# Check 4 is automated here; re-run on the scale stand to close Phase 3 item 3.
set -Eeuo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
NAMESPACE="${NAMESPACE:-agentflow}"
RELEASE_NAME="${RELEASE_NAME:-agentflow}"
# A support-tenant key with webhook scope (matches k8s_smoke_test.sh defaults /
# values-staging.yaml fixtures).
API_KEY="${API_KEY:-af-prod-agent-ops-def456}"
MIN_REPLICAS="${MIN_REPLICAS:-2}"
# Public https URL that passes the egress guard and accepts POST with 2xx so the
# inline delivery marks the queue row delivered (no redrive noise in the logs).
# example.com returns 405 Method Not Allowed on POST and would force redrive
# (a second delivery_id), which confuses the exactly-one assertion.
WEBHOOK_URL="${WEBHOOK_URL:-https://httpbin.org/post}"
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

# Check 4 — alert dispatcher default poll is 60s; wait >1 full tick so both
# pods have had a chance to race claim_alert_tick for the same rule.
ALERT_WAIT_SECONDS="${ALERT_WAIT_SECONDS:-150}"
ALERT_POLL_SECONDS="${ALERT_POLL_SECONDS:-5}"
# error_rate over 1h is 0 when the only journal rows are non-deadletter
# (Check 3 insert is enough). below 1.0 therefore always fires on a healthy stand.
ALERT_METRIC="${ALERT_METRIC:-error_rate}"
ALERT_WINDOW="${ALERT_WINDOW:-1h}"
ALERT_CONDITION="${ALERT_CONDITION:-below}"
ALERT_THRESHOLD="${ALERT_THRESHOLD:-1.0}"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

webhook_id=""
alert_id=""
cleanup() {
  if [[ -n "${webhook_id}" ]]; then
    curl -fsS -X DELETE -H "X-API-Key: $API_KEY" \
      "$BASE_URL/v1/webhooks/$webhook_id" >/dev/null 2>&1 || true
  fi
  if [[ -n "${alert_id}" ]]; then
    curl -fsS -X DELETE -H "X-API-Key: $API_KEY" \
      "$BASE_URL/v1/alerts/$alert_id" >/dev/null 2>&1 || true
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

# --- Check 4: one alert page per incident (claim_alert_tick single-flight) ----
echo "==> [Check 4] exactly one alert.triggered page for one firing rule across pods"

# Check 3 left a non-deadletter pipeline_events row, so error_rate is 0 (or at
# least < 1.0). A rule with condition=below / threshold=1.0 must fire once the
# dispatcher ticks. Without postgres claim_alert_tick both pods would each
# page → two successful alert.triggered history rows.
alert_body=$(ALERT_METRIC="$ALERT_METRIC" ALERT_WINDOW="$ALERT_WINDOW" \
  ALERT_CONDITION="$ALERT_CONDITION" ALERT_THRESHOLD="$ALERT_THRESHOLD" \
  WEBHOOK_URL="$WEBHOOK_URL" python3 -c '
import json, os
print(json.dumps({
    "name": "replica-e4-single-page",
    "metric": os.environ["ALERT_METRIC"],
    "window": os.environ["ALERT_WINDOW"],
    "condition": os.environ["ALERT_CONDITION"],
    "threshold": float(os.environ["ALERT_THRESHOLD"]),
    "webhook_url": os.environ["WEBHOOK_URL"],
    "cooldown_minutes": 60,
}))
')
alert_reg=$(curl -fsS -X POST \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "$alert_body" \
  "$BASE_URL/v1/alerts")
alert_id=$(printf '%s' "$alert_reg" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
[[ -n "$alert_id" ]] || fail "alert create returned no id: $alert_reg"
echo "    registered alert_id=$alert_id metric=$ALERT_METRIC $ALERT_CONDITION $ALERT_THRESHOLD window=$ALERT_WINDOW"

deadline=$(( $(date +%s) + ALERT_WAIT_SECONDS ))
triggered_ok=0
history_count=0
while (( $(date +%s) < deadline )); do
  hist_json=$(curl -fsS -H "X-API-Key: $API_KEY" \
    "$BASE_URL/v1/alerts/$alert_id/history")
  counts=$(printf '%s' "$hist_json" | python3 -c '
import json, sys
hist = json.load(sys.stdin).get("history") or []
# One incident page = one successful initial fire. Failed delivery attempts
# retry and would inflate the count — those are not multi-pod split pages.
ok = [
    h for h in hist
    if str(h.get("event_type") or "") == "alert.triggered" and h.get("success") is True
]
print(len(ok), len(hist))
')
  # shellcheck disable=SC2086
  set -- $counts
  triggered_ok=${1:-0}
  history_count=${2:-0}
  if (( triggered_ok >= 1 )); then
    break
  fi
  sleep "$ALERT_POLL_SECONDS"
done

(( triggered_ok >= 1 )) || fail "no successful alert.triggered within ${ALERT_WAIT_SECONDS}s (dispatcher idle, metric not firing, or delivery failing)"
(( triggered_ok == 1 )) || fail "expected exactly 1 successful alert.triggered page, got ${triggered_ok} (split page across pods?)"
pass "exactly one alert.triggered page for alert_id=$alert_id (${history_count} history row(s))"

echo "==> replica-correctness verify OK (Checks 1-4)"
