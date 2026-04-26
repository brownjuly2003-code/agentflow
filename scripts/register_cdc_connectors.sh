#!/usr/bin/env bash
set -euo pipefail

CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}"

wait_for_connect() {
  for _ in $(seq 1 60); do
    if curl -fsS "${CONNECT_URL}/connectors" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  echo "Kafka Connect did not become ready at ${CONNECT_URL}" >&2
  return 1
}

put_postgres_connector() {
  curl -fsS -X PUT \
    -H "Content-Type: application/json" \
    --data-binary @- \
    "${CONNECT_URL}/connectors/agentflow-postgres-cdc/config" <<'JSON'
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "tasks.max": "1",
  "database.hostname": "${file:/opt/connect/secrets/postgres.properties:hostname}",
  "database.port": "5432",
  "database.user": "${file:/opt/connect/secrets/postgres.properties:user}",
  "database.password": "${file:/opt/connect/secrets/postgres.properties:password}",
  "database.dbname": "agentflow_demo",
  "topic.prefix": "cdc.postgres",
  "plugin.name": "pgoutput",
  "slot.name": "agentflow_postgres_slot",
  "publication.name": "agentflow_cdc_publication",
  "publication.autocreate.mode": "filtered",
  "table.include.list": "public.orders_v2,public.users_enriched",
  "snapshot.mode": "initial",
  "heartbeat.interval.ms": "30000",
  "signal.data.collection": "agentflow_demo.public.debezium_signal",
  "key.converter": "org.apache.kafka.connect.json.JsonConverter",
  "value.converter": "org.apache.kafka.connect.json.JsonConverter",
  "key.converter.schemas.enable": "false",
  "value.converter.schemas.enable": "false",
  "custom.metric.tags": "service=agentflow,source=postgres"
}
JSON
}

put_mysql_connector() {
  curl -fsS -X PUT \
    -H "Content-Type: application/json" \
    --data-binary @- \
    "${CONNECT_URL}/connectors/agentflow-mysql-cdc/config" <<JSON
{
  "connector.class": "io.debezium.connector.mysql.MySqlConnector",
  "tasks.max": "1",
  "database.hostname": "\${file:/opt/connect/secrets/mysql.properties:hostname}",
  "database.port": "3306",
  "database.user": "\${file:/opt/connect/secrets/mysql.properties:user}",
  "database.password": "\${file:/opt/connect/secrets/mysql.properties:password}",
  "database.server.id": "223345",
  "topic.prefix": "cdc.mysql",
  "database.include.list": "agentflow_demo",
  "table.include.list": "agentflow_demo.products_current,agentflow_demo.sessions_aggregated",
  "snapshot.mode": "initial",
  "heartbeat.interval.ms": "30000",
  "schema.history.internal.kafka.bootstrap.servers": "${KAFKA_BOOTSTRAP_SERVERS}",
  "schema.history.internal.kafka.topic": "schemahistory.cdc.mysql.agentflow_demo",
  "key.converter": "org.apache.kafka.connect.json.JsonConverter",
  "value.converter": "org.apache.kafka.connect.json.JsonConverter",
  "key.converter.schemas.enable": "false",
  "value.converter.schemas.enable": "false",
  "custom.metric.tags": "service=agentflow,source=mysql"
}
JSON
}

wait_for_connector() {
  local name="$1"
  local status_file
  status_file="$(mktemp)"
  for _ in $(seq 1 30); do
    if curl -fsS "${CONNECT_URL}/connectors/${name}/status" >"${status_file}"; then
      if python - "${status_file}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)

connector_running = payload.get("connector", {}).get("state") == "RUNNING"
tasks = payload.get("tasks", [])
tasks_running = bool(tasks) and all(task.get("state") == "RUNNING" for task in tasks)
raise SystemExit(0 if connector_running and tasks_running else 1)
PY
      then
        rm -f "${status_file}"
        return 0
      fi
    fi
    sleep 2
  done
  cat "${status_file}" >&2 || true
  rm -f "${status_file}"
  echo "Connector ${name} did not reach RUNNING state" >&2
  return 1
}

wait_for_connect
put_postgres_connector >/dev/null
put_mysql_connector >/dev/null
wait_for_connector agentflow-postgres-cdc
wait_for_connector agentflow-mysql-cdc
echo "CDC connectors are RUNNING."
