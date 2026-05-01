# Operational Runbook

## Quick Reference

| Service | Local URL | Health check |
|---------|-----------|-------------|
| Agent API | http://localhost:8000/docs | `curl http://localhost:8000/v1/health` |
| Kafka | localhost:9092 | `kafka-broker-api-versions --bootstrap-server localhost:9092` |
| Flink UI | http://localhost:8081 | `curl http://localhost:8081/overview` |
| MinIO | http://localhost:9001 | `curl http://localhost:9000/minio/health/live` |
| Prometheus | http://localhost:9090 | `curl http://localhost:9090/-/healthy` |
| Grafana | http://localhost:3000 | `curl http://localhost:3000/api/health` |
| Jaeger | http://localhost:16686 | `curl -I http://localhost:16686` |
| Toxiproxy API | http://localhost:8474 | `curl http://localhost:8474/proxies` |

## Local Pipeline Operations

### Start the local demo (Docker Redis only)

```bash
make demo          # Seeds 500 events, starts Redis via Docker Compose, starts API
```

### Run continuous local pipeline

```bash
make pipeline      # 10 events/sec, writes to agentflow_demo.duckdb
```

### Inspect local DuckDB

```bash
duckdb agentflow_demo.duckdb
```

```sql
SELECT COUNT(*) FROM pipeline_events;
SELECT * FROM orders_v2 ORDER BY created_at DESC LIMIT 5;
SELECT topic, COUNT(*) FROM pipeline_events GROUP BY topic;
```

### Reset local data

```bash
make clean         # Removes .duckdb files + caches
make demo          # Start fresh
```

## Docker Stack Operations

### Start the prod-like stack

```bash
docker compose -f docker-compose.prod.yml up -d
python scripts/wait_for_services.py --url http://127.0.0.1:8000 --timeout 120
```

Use this path for E2E checks and incidents that depend on Redis, Jaeger, Prometheus, or Grafana.

### Running Flink locally with Docker

```bash
make flink-local
```

This builds the local Python 3.11 Flink image, starts the required Kafka, MinIO, and Flink services, and submits `src/processing/flink_jobs/stream_processor.py` to the local cluster.

Verify the run here:
- Flink Web UI: http://localhost:8081
- Valid events: `events.validated`
- Invalid events: `events.deadletter`

### Run local CDC capture

```bash
docker compose -f docker-compose.yml -f docker-compose.cdc.yml build kafka-connect
docker compose -f docker-compose.yml -f docker-compose.cdc.yml up -d kafka cdc-kafka-init postgres-source mysql-source kafka-connect
docker compose -f docker-compose.yml -f docker-compose.cdc.yml run --rm cdc-register-connectors
```

Verify connector state:

```bash
curl -fsS http://localhost:8083/connectors/agentflow-postgres-cdc/status
curl -fsS http://localhost:8083/connectors/agentflow-mysql-cdc/status
```

Run the optional Docker CDC integration test against the running stack:

```bash
AGENTFLOW_RUN_CDC_DOCKER=1 python -m pytest -p no:schemathesis tests/integration/test_cdc_capture.py -q
```

Stop the local CDC stack when finished:

```bash
docker compose -f docker-compose.yml -f docker-compose.cdc.yml down
```

Kafka auto-create is disabled locally, so `cdc-kafka-init` pre-creates raw table topics, Debezium heartbeat topics, the MySQL signal topic `cdc.mysql`, and Kafka Connect internal topics. The MySQL schema history topic must use `cleanup.policy=delete` with unlimited retention; Debezium 3.5 JSON schema-history records can be keyless, and a compacted topic rejects those records.

For Kubernetes installs, choose one Kafka Connect source-credential mode:

- Demo/staging chart-managed credentials: keep `secrets.create=true` and leave `secrets.existingSecret` empty.
- Externally managed credentials: set `secrets.create=false` and set `secrets.existingSecret` to a Kubernetes Secret that contains `postgres.properties` and `mysql.properties`.

The chart schema rejects mixed or missing modes so a rendered deployment cannot reference a missing source-credential Secret.

Production source attachment has a separate gate. Before creating any connector
for a real Postgres or MySQL database, complete
[Production CDC Source Onboarding](operations/cdc-production-onboarding.md).

### Restart a Flink job

```bash
# List running jobs
curl http://localhost:8081/jobs

# Cancel a job (it will restart from last checkpoint)
curl -X PATCH http://localhost:8081/jobs/<job-id>?mode=cancel

# Resubmit
flink run -py src/processing/flink_jobs/stream_processor.py
```

### Check Kafka consumer lag

```bash
kafka-consumer-groups --bootstrap-server localhost:9092 \
  --group agentflow-stream-processor --describe
```

If lag > 100k: Flink is behind. Check Flink UI for backpressure indicators.

### Reset a consumer group

```bash
# Stop the Flink job first, then:
kafka-consumer-groups --bootstrap-server localhost:9092 \
  --group agentflow-stream-processor \
  --reset-offsets --to-latest --execute \
  --topic orders.raw
```

### Inspect dead letter events

```bash
kafka-console-consumer --bootstrap-server localhost:9092 \
  --topic events.deadletter --from-beginning --max-messages 10 | jq .
```

### Launch kind staging

```bash
bash scripts/k8s_staging_up.sh
bash scripts/k8s_staging_down.sh
```

`scripts/k8s_staging_up.sh` expects `docker`, `kubectl`, `helm`, and `kind` on the path. It builds the API image, loads it into kind, installs the Helm chart, and runs a smoke test.

## Incident Response

### API does not respond

1. Check `curl http://localhost:8000/v1/health`.
2. If the endpoint times out, inspect `docker compose -f docker-compose.prod.yml ps`.
3. Read the latest API logs: `docker compose -f docker-compose.prod.yml logs agentflow-api --tail 50`.
4. Open Jaeger at `http://localhost:16686` and look for hanging `http.request`, `nl_to_sql`, or `duckdb.query` spans.
5. Restart only the API first: `docker compose -f docker-compose.prod.yml restart agentflow-api`.
6. If the API still cannot become healthy, switch to the recovery steps in `docs/disaster-recovery.md`.

### Pipeline lag > 60s

1. Check Grafana and compare `/v1/health` freshness against the expected window.
2. Measure Kafka lag with `kafka-consumer-groups --bootstrap-server localhost:9092 --group agentflow-stream-processor --describe`.
3. If Kafka lag is high, inspect broker disk and partition skew before changing partition count.
4. If Flink shows backpressure, inspect TaskManager memory and parallelism in the Flink UI.
5. If the sink is slow, check Iceberg or object-store write latency and run the relevant compaction or snapshot cleanup job.

### Flink job failed

1. Check Flink UI -> Jobs -> Failed -> Exception.
2. Look for one of the common causes: OOM (`taskmanager.memory.process.size`), checkpoint timeout (`execution.checkpointing.timeout`), or Kafka connectivity problems.
3. Let Flink restart from the last checkpoint once.
4. If it fails again with the same exception, fix the root cause before forcing another restart.

### Dead letter topic filling up

1. Check aggregate status: `curl -H "X-API-Key: <key>" http://localhost:8000/v1/deadletter/stats`.
2. List the newest failures: `curl -H "X-API-Key: <key>" "http://localhost:8000/v1/deadletter?page=1&page_size=20"`.
3. Inspect one event in detail to confirm whether the issue is schema drift, semantic validation, or downstream delivery.
4. If the payload is correctable, replay it through `POST /v1/deadletter/{event_id}/replay`.
5. If the source is producing invalid payloads, stop replay attempts, notify the source owner, and add filtering or contract fixes first.

### Alert storm or duplicate alerts

1. List active rules with `curl -H "X-API-Key: <key>" http://localhost:8000/v1/alerts`.
2. Inspect recent history with `curl -H "X-API-Key: <key>" http://localhost:8000/v1/alerts/<alert_id>/history`.
3. Check whether the rule is flapping or escalating too aggressively in `config/alerts.yaml`.
4. If the rule is noisy and unactionable, temporarily disable it with `DELETE /v1/alerts/{alert_id}` or update the threshold and cooldown.
5. After the metric stabilizes, recreate or update the alert and confirm the webhook history has normalized.

### Webhook deliveries failing

1. List registrations with `curl -H "X-API-Key: <key>" http://localhost:8000/v1/webhooks`.
2. Inspect the failing webhook logs with `curl -H "X-API-Key: <key>" http://localhost:8000/v1/webhooks/<webhook_id>/logs`.
3. Trigger a synthetic delivery through `POST /v1/webhooks/{webhook_id}/test`.
4. If the failure happens only in kind staging, verify the host loopback relay configured by `scripts/k8s_staging_up.sh`.
5. Once the target endpoint is healthy again, replay or re-trigger the expected event path.

### API key rotation stuck in grace period

1. Check rotation state with `curl -H "X-Admin-Key: <admin-key>" http://localhost:8000/v1/admin/keys/<key_id>/rotation-status`.
2. Verify `requests_on_old_key_last_hour`; if it is non-zero, some client still uses the old secret.
3. Roll out the new key to every caller and wait until old-key traffic drops to zero.
4. Revoke the old secret with `POST /v1/admin/keys/{key_id}/revoke-old`.
5. Confirm the old key now returns `401` and the new key still passes `/v1/health`.

### No events flowing (zero throughput)

1. Check Kafka first: `kafka-broker-api-versions --bootstrap-server localhost:9092`.
2. Confirm producers are still sending data and inspect their logs.
3. Verify the Flink job is running and consuming from the expected topics.
4. Check network reachability and DNS between Flink, Kafka, and the sink services.
5. If you recently changed chaos settings, confirm Toxiproxy has been reset and all proxies are enabled.

## Disaster Recovery

For restore drills, backup verification, or host loss scenarios, use [docs/disaster-recovery.md](disaster-recovery.md).

## Maintenance

### Weekly
- Review dead letter topic volume (should be < 0.1% of total)
- Check Kafka disk usage (alert at 80%)
- Review Grafana dashboards for anomalies
- Review noisy alerts and webhook delivery failures before they become chronic incidents

### Monthly
- Iceberg snapshot expiry: `CALL system.expire_snapshots('table', older_than => 30d)`
- Iceberg compaction: `CALL system.rewrite_data_files('table')`
- Review and rotate API keys
- Run `pytest tests/chaos/ -v --tb=short` against the current compose stack
- Cost review: compare actual vs projected spend
