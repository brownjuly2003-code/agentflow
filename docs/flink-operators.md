# Flink Operators

## Session Aggregation

`src/processing/flink_jobs/session_aggregation.py` aggregates events into per-user sessions with a 30-minute inactivity gap.

Behavior:
- key: `user_id`
- state: `start_time`, `last_time`, `event_count`, `total_value`
- close condition: `event_time - last_time > 30 minutes`
- output: `session_start`, `session_end`, `event_count`, `total_value`, `status=closed`

The module keeps a pure-Python `SessionAggregator` for deterministic tests and uses the same snapshot format inside the Flink `MapState` adapter.

## Checkpointing

`src/processing/flink_jobs/checkpointing.py` configures production-safe defaults:
- interval: 60 seconds
- mode: exactly-once
- min pause between checkpoints: 30 seconds
- timeout: 120 seconds
- max concurrent checkpoints: 1
- externalized checkpoints: retain on cancellation
- storage: `FLINK_CHECKPOINT_DIR` or `file:///tmp/flink-checkpoints`

This allows session state to survive a job restart after the latest completed checkpoint is restored.

## Local Run

1. Install the Flink extra: `pip install -e .[flink]`
2. Export `KAFKA_BOOTSTRAP_SERVERS` and optionally `FLINK_CHECKPOINT_DIR`
3. Submit the job: `flink run -py src/processing/flink_jobs/session_aggregation.py`

Default topics:
- source: `events.validated`
- sink: `sessions.aggregated`

Override them with:
- `FLINK_SOURCE_TOPIC`
- `FLINK_SESSION_SINK_TOPIC`

## Tests

Run the Task 7 regression suite with:

```bash
python -m pytest tests/integration/test_flink_session.py -q
```

Covered scenarios:
- session opens on first event
- session stays open while events arrive within the gap
- session closes when the gap exceeds 30 minutes
- state snapshot/restore simulates crash recovery
- users are isolated from each other
- checkpointing uses exactly-once settings
