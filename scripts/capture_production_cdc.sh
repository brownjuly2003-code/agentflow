#!/usr/bin/env bash
# Production CDC capture evidence run (backlog item 19).
#
# Registers a Debezium Postgres connector against the REAL production Neon
# database (operator-owned, solo-org roles recorded in
# docs/operations/cdc-production-onboarding.md), captures the initial
# snapshot of the approved table scope into Kafka, writes an evidence
# report, and tears everything down (connector, publication, replication
# slot). Intended to run only from the dispatch-only
# cdc-production-capture.yml workflow.
#
# Required environment:
#   CDC_NEON_HOSTNAME, CDC_NEON_USER, CDC_NEON_PASSWORD, CDC_NEON_DBNAME
#   CONNECT_URL   (default http://localhost:8083)
#   KAFKA_CONTAINER (default kafka)
set -euo pipefail

CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
KAFKA_CONTAINER="${KAFKA_CONTAINER:-kafka}"
CONNECTOR_NAME="agentflow-prod-neon-cdc"
SLOT_NAME="agentflow_prod_capture_slot"
PUBLICATION_NAME="agentflow_prod_capture_publication"
TABLE_SCOPE="public.vacancies"
TOPIC="cdc.prod.public.vacancies"
EVIDENCE_DIR="${EVIDENCE_DIR:-.artifacts/cdc-production}"
PGURI="postgresql://${CDC_NEON_USER}:${CDC_NEON_PASSWORD}@${CDC_NEON_HOSTNAME}/${CDC_NEON_DBNAME}?sslmode=require"

mkdir -p "${EVIDENCE_DIR}"
EVIDENCE="${EVIDENCE_DIR}/capture-evidence.md"

psql_run() {
  psql "${PGURI}" -X -A -t -c "$1"
}

teardown() {
  echo "--- teardown ---"
  curl -fsS -X DELETE "${CONNECT_URL}/connectors/${CONNECTOR_NAME}" || true
  sleep 5
  psql_run "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = '${SLOT_NAME}';" || true
  psql_run "DROP PUBLICATION IF EXISTS ${PUBLICATION_NAME};" || true
  local leftover
  leftover=$(psql_run "SELECT count(*) FROM pg_replication_slots WHERE slot_name = '${SLOT_NAME}';")
  echo "leftover capture slots: ${leftover}"
  {
    echo
    echo "## Teardown"
    echo
    echo "- Connector deleted, publication dropped."
    echo "- Leftover \`${SLOT_NAME}\` slots after teardown: \`${leftover}\` (must be 0)."
  } >> "${EVIDENCE}"
  if [ "${leftover}" != "0" ]; then
    echo "ERROR: replication slot ${SLOT_NAME} still present after teardown" >&2
    exit 1
  fi
}
trap teardown EXIT

wait_for_connect() {
  # The REST port answers GET /connectors before the herder can accept
  # connector creation (a 500-on-PUT race during worker startup). Wait until
  # the Postgres connector plugin is actually loaded — that signals the worker
  # has finished its plugin scan and the herder is ready.
  for _ in $(seq 1 90); do
    if curl -fsS "${CONNECT_URL}/connector-plugins" 2>/dev/null | grep -q "PostgresConnector"; then
      return 0
    fi
    sleep 2
  done
  echo "Kafka Connect did not become ready at ${CONNECT_URL}" >&2
  return 1
}

echo "--- preflight ---"
WAL_LEVEL=$(psql_run "SHOW wal_level;")
ROW_COUNT=$(psql_run "SELECT count(*) FROM ${TABLE_SCOPE};")
BASELINE_SLOTS=$(psql_run "SELECT count(*) FROM pg_replication_slots;")
echo "wal_level=${WAL_LEVEL} rows=${ROW_COUNT} baseline_slots=${BASELINE_SLOTS}"
if [ "${WAL_LEVEL}" != "logical" ]; then
  echo "ERROR: wal_level is '${WAL_LEVEL}', not 'logical'. Enable logical replication in the Neon console first." >&2
  exit 1
fi

wait_for_connect

echo "--- register connector ---"
cat > /tmp/connector_config.json <<JSON
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "tasks.max": "1",
  "database.hostname": "\${file:/opt/connect/secrets/neon.properties:hostname}",
  "database.port": "5432",
  "database.user": "\${file:/opt/connect/secrets/neon.properties:user}",
  "database.password": "\${file:/opt/connect/secrets/neon.properties:password}",
  "database.dbname": "\${file:/opt/connect/secrets/neon.properties:dbname}",
  "database.sslmode": "require",
  "topic.prefix": "cdc.prod",
  "plugin.name": "pgoutput",
  "slot.name": "${SLOT_NAME}",
  "publication.name": "${PUBLICATION_NAME}",
  "publication.autocreate.mode": "filtered",
  "table.include.list": "${TABLE_SCOPE}",
  "snapshot.mode": "initial",
  "key.converter": "org.apache.kafka.connect.json.JsonConverter",
  "value.converter": "org.apache.kafka.connect.json.JsonConverter",
  "key.converter.schemas.enable": "false",
  "value.converter.schemas.enable": "false",
  "custom.metric.tags": "service=agentflow,source=neon-production"
}
JSON

# Even after the plugin loads, the herder can briefly 500/503 a connector
# create while it finishes rebalancing. Retry the PUT on any non-2xx instead
# of letting `set -e` kill the run on the first transient failure.
registered=0
for _ in $(seq 1 30); do
  REG_CODE=$(curl -s -o /tmp/connector_register_resp.json -w '%{http_code}' -X PUT \
    -H "Content-Type: application/json" \
    --data-binary @/tmp/connector_config.json \
    "${CONNECT_URL}/connectors/${CONNECTOR_NAME}/config" || echo "000")
  if [ "${REG_CODE}" = "200" ] || [ "${REG_CODE}" = "201" ]; then
    registered=1
    echo "connector registered (HTTP ${REG_CODE})"
    break
  fi
  echo "register attempt -> HTTP ${REG_CODE}; worker not ready, retrying"
  sleep 5
done
if [ "${registered}" != "1" ]; then
  echo "ERROR: connector registration failed after retries (last HTTP ${REG_CODE})" >&2
  cat /tmp/connector_register_resp.json 2>/dev/null || true
  exit 1
fi

echo "--- wait for RUNNING ---"
STATE=""
for _ in $(seq 1 60); do
  STATE=$(curl -fsS "${CONNECT_URL}/connectors/${CONNECTOR_NAME}/status" | python3 -c 'import json,sys; s=json.load(sys.stdin); tasks=s.get("tasks") or [{}]; print(s["connector"]["state"], tasks[0].get("state","-"))' || echo "pending -")
  echo "connector state: ${STATE}"
  if [ "${STATE}" = "RUNNING RUNNING" ]; then
    break
  fi
  if echo "${STATE}" | grep -q "FAILED"; then
    curl -fsS "${CONNECT_URL}/connectors/${CONNECTOR_NAME}/status" || true
    exit 1
  fi
  sleep 5
done
if [ "${STATE}" != "RUNNING RUNNING" ]; then
  echo "ERROR: connector did not reach RUNNING" >&2
  exit 1
fi

echo "--- wait for snapshot to land in Kafka ---"
CAPTURED=0
for _ in $(seq 1 90); do
  # The topic does not exist until the snapshot writes its first record, so
  # GetOffsetShell fails on early iterations; tolerate it under pipefail/set -e
  # and keep polling instead of dying on the first miss.
  CAPTURED=$(docker exec "${KAFKA_CONTAINER}" kafka-run-class kafka.tools.GetOffsetShell \
    --broker-list localhost:9092 --topic "${TOPIC}" --time -1 2>/dev/null \
    | awk -F: '{sum += $3} END {print sum+0}' || true)
  CAPTURED=${CAPTURED:-0}
  echo "captured events: ${CAPTURED}/${ROW_COUNT}"
  if [ "${CAPTURED}" -ge "${ROW_COUNT}" ]; then
    break
  fi
  sleep 10
done
if [ "${CAPTURED}" -lt "${ROW_COUNT}" ]; then
  echo "ERROR: captured ${CAPTURED} events, expected at least ${ROW_COUNT}" >&2
  exit 1
fi

echo "--- sample event (redacted keys only) ---"
SAMPLE_KEYS=$(docker exec "${KAFKA_CONTAINER}" kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic "${TOPIC}" \
  --from-beginning --max-messages 1 --timeout-ms 30000 2>/dev/null \
  | python3 -c 'import json,sys; e=json.loads(sys.stdin.read()); p=e.get("payload",e); a=p.get("after") or {}; print(sorted(a.keys()))' || true)
SAMPLE_KEYS=${SAMPLE_KEYS:-"(sample consumer returned no message)"}
echo "sample event field names: ${SAMPLE_KEYS}"

CONNECTOR_STATUS=$(curl -fsS "${CONNECT_URL}/connectors/${CONNECTOR_NAME}/status")

{
  echo "# Production CDC Capture Evidence"
  echo
  echo "Generated by workflow run: ${GITHUB_SERVER_URL:-local}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-local}"
  echo
  echo "## Source"
  echo
  echo "- Real production Neon Postgres (operator-owned), database \`${CDC_NEON_DBNAME}\`, table scope \`${TABLE_SCOPE}\`."
  echo "- Preflight: \`wal_level=${WAL_LEVEL}\`, source rows \`${ROW_COUNT}\`, pre-existing replication slots \`${BASELINE_SLOTS}\` (untouched)."
  echo
  echo "## Capture"
  echo
  echo "- Connector \`${CONNECTOR_NAME}\` (Debezium Postgres, pgoutput, TLS required) reached \`RUNNING/RUNNING\`."
  echo "- Initial snapshot captured \`${CAPTURED}\` events into Kafka topic \`${TOPIC}\` (source rows: \`${ROW_COUNT}\`)."
  echo "- Sample event field names (values withheld): \`${SAMPLE_KEYS}\`"
  echo
  echo "## Connector status (raw)"
  echo
  echo '```json'
  echo "${CONNECTOR_STATUS}"
  echo '```'
} > "${EVIDENCE}"

echo "--- evidence written to ${EVIDENCE} ---"
