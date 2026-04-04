# Operational Runbook

## Quick Reference

| Service | Local URL | Health check |
|---------|-----------|-------------|
| Kafka | localhost:9092 | `kafka-broker-api-versions --bootstrap-server localhost:9092` |
| Flink UI | http://localhost:8081 | `curl http://localhost:8081/overview` |
| MinIO | http://localhost:9001 | `curl http://localhost:9000/minio/health/live` |
| Agent API | http://localhost:8000/docs | `curl http://localhost:8000/v1/health` |
| Prometheus | http://localhost:9090 | `curl http://localhost:9090/-/healthy` |
| Grafana | http://localhost:3000 | `curl http://localhost:3000/api/health` |

## Common Operations

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

## Incident Response

### Pipeline latency > 30s (SLA breach)

1. **Check Grafana** → Pipeline Health dashboard
2. **Identify bottleneck**: Kafka lag? Flink backpressure? Slow sink?
3. **If Kafka lag high**: Check broker disk usage, increase partitions if needed
4. **If Flink backpressure**: Check TaskManager memory, increase parallelism
5. **If sink slow**: Check S3/Iceberg write latency, compact if needed

### Flink job failed

1. **Check Flink UI** → Jobs → Failed → Exception tab
2. **Common causes**:
   - OOM: Increase TaskManager memory (`taskmanager.memory.process.size`)
   - Checkpoint timeout: Increase `execution.checkpointing.timeout`
   - Kafka connection: Verify bootstrap servers, check Kafka health
3. **Flink auto-restarts** from last checkpoint. If it keeps failing, fix root cause first.

### Dead letter topic filling up

1. **Read recent DL events**: See command above
2. **Identify pattern**: Same event_type? Same source? Same error?
3. **If schema changed**: Update Pydantic models in `src/ingestion/schemas/events.py`
4. **If source is sending garbage**: Contact source team, add source-level filtering

### No events flowing (zero throughput)

1. **Check Kafka**: `kafka-broker-api-versions` — are brokers alive?
2. **Check producers**: Is the event producer running? Check its logs.
3. **Check Flink**: Is the job running? Check Flink UI.
4. **Check network**: Can Flink reach Kafka? DNS resolution? Security groups?

## Maintenance

### Weekly
- Review dead letter topic volume (should be < 0.1% of total)
- Check Kafka disk usage (alert at 80%)
- Review Grafana dashboards for anomalies

### Monthly
- Iceberg snapshot expiry: `CALL system.expire_snapshots('table', older_than => 30d)`
- Iceberg compaction: `CALL system.rewrite_data_files('table')`
- Review and rotate API keys
- Cost review: compare actual vs projected spend
