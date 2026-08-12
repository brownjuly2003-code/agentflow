# Flink Operators

## Session Aggregation

`src/processing/flink_jobs/session_aggregator.py` is the single canonical
session job. It consumes validated events and closes tenant-scoped sessions
after a 30-minute inactivity gap.

Behavior:
- input key: `(tenant, session_id)`; legacy `tenant_id` input remains compatible
- time model: event-time with 10-second bounded out-of-orderness
- close condition: an event-time timer at `last_event_ts + 30 minutes`
- late-event policy: events at or behind the current watermark are dropped and
  counted in the Flink `late_events_dropped` metric
- bounded state: unique pages and products default to 1,000 entries each;
  `FLINK_SESSION_MAX_UNIQUE_PAGES` and
  `FLINK_SESSION_MAX_UNIQUE_PRODUCTS` tune the caps
- output reports `pages_truncated` and `products_truncated` when a cap was hit

`session_aggregation.py` is a compatibility adapter only. Its Flink build and
launch functions delegate to `session_aggregator.py`; it contains no second
Flink operator.

## Stream processor Kafka startup

The operator-managed stream processor defaults to
`flinkJob.kafkaStartupMode: earliest-offset`, preserving clean-bootstrap and
replay behavior. For a deliberately stateless cutover where the existing
consumer group has known committed offsets, set it to `group-offsets`; Helm
passes the value as `AGENTFLOW_KAFKA_STARTUP_MODE`. The job rejects other
startup modes instead of silently choosing a different offset boundary.

## Checkpointing

`src/processing/flink_jobs/checkpointing.py` provides reusable checkpoint defaults:
- interval: 60 seconds
- mode: exactly-once
- min pause between checkpoints: 30 seconds
- timeout: 120 seconds
- max concurrent checkpoints: 1
- externalized checkpoints: retain on cancellation
- storage: `FLINK_CHECKPOINT_DIR` or `file:///tmp/flink-checkpoints`

This allows session state to survive a job restart after the latest completed checkpoint is restored.

The operator-managed stream and session jobs use
`flinkJob.checkpointIntervalMs` (30 seconds by default) and
`flinkJob.checkpointMinPauseMs` (10 seconds by default). Helm applies both to
the `FlinkDeployment` configuration and passes them to the Python jobs as
`FLINK_CHECKPOINT_INTERVAL_MS` and `FLINK_CHECKPOINT_MIN_PAUSE_MS`, so a short
checkpoint interval is not silently constrained by a fixed pause.

For constrained Kubernetes profiles, `flinkJob.memoryConfiguration` passes an
explicit process-memory breakdown to both operator-managed jobs. Keys are
limited to `jobmanager.memory.*` and `taskmanager.memory.*`, and values must be
strings such as `"384m"`. The map is empty by default, so the standard 2 GiB
profile keeps Flink's defaults.

The following breakdown has been runtime-verified with a 896 MiB JobManager
and a 768 MiB TaskManager:

```yaml
flinkJob:
  jobManager:
    memory: 896m
  taskManager:
    memory: 768m
  memoryConfiguration:
    jobmanager.memory.heap.size: "384m"
    jobmanager.memory.off-heap.size: "64m"
    jobmanager.memory.jvm-metaspace.size: "256m"
    jobmanager.memory.jvm-overhead.min: "128m"
    jobmanager.memory.jvm-overhead.max: "256m"
    taskmanager.memory.framework.heap.size: "64m"
    taskmanager.memory.framework.off-heap.size: "64m"
    taskmanager.memory.task.heap.size: "192m"
    taskmanager.memory.managed.size: "32m"
    taskmanager.memory.network.min: "32m"
    taskmanager.memory.network.max: "32m"
    taskmanager.memory.jvm-metaspace.size: "128m"
    taskmanager.memory.jvm-overhead.min: "128m"
    taskmanager.memory.jvm-overhead.max: "256m"
```

## Local Run

1. Install the Flink runtime manifest **in its own venv**:
   `pip install -r src/processing/flink_jobs/requirements.txt`.
   There is no `[flink]` extra: apache-flink's beam chain caps `pyarrow<17`
   while the core package pins `pyarrow>=17`, so the two can never share one
   environment. The job imports nothing from agentflow, so it does not need
   the package.
2. Export `KAFKA_BOOTSTRAP_SERVERS` and optionally `FLINK_CHECKPOINT_DIR`
3. Submit the job:
   `flink run -py src/processing/flink_jobs/session_aggregator.py`

Default topics:
- source: `events.validated`
- sink: `sessions.aggregated`

Override them with:
- `FLINK_SESSION_SOURCE_TOPIC`
- `FLINK_SESSION_SINK_TOPIC`

The Helm production workload renders exactly this implementation when
`flinkJob.enabled=true` and `flinkJob.sessions.enabled=true` (the default
inside the disabled-by-default Flink workload).

The production image extends the digest-pinned official
`flink:2.3.0-scala_2.12-java17` image so the Kubernetes Operator can invoke the
standard `/docker-entrypoint.sh`. PyFlink and job dependencies live in
`/opt/pyflink-venv`; both rendered jobs pass that interpreter through
`-pyclientexec`.

## Kubernetes Operator 1.15 compatibility

Install the pinned Apache Flink Kubernetes Operator 1.15.0 chart before the
AgentFlow chart. The 1.15.0 operator code recognizes `v2_3`, but its published
generated `FlinkDeployment` CRD enum ends at `v2_2`. After installing that
exact operator release, repair the CRD before enabling `flinkJob`:

```bash
python scripts/patch_flink_operator_1_15_crd.py
```

The command is idempotent and fail-closed: it adds only `v2_3`, only when the
existing enum exactly matches the published 1.15.0 schema, and refuses unknown
or newer CRD layouts. Do not use this version-specific patch with another
operator release.

## Tests

Run the Task 7 regression suite with:

```bash
python -m pytest tests/unit/test_session_aggregator.py tests/integration/test_flink_session.py -q
```

Covered scenarios:
- an idle user closes on an event-time timer without a following event
- out-of-order events do not shorten the active timer
- late events follow the documented drop-and-count policy
- state caps and truncation metadata
- identical session IDs remain isolated across tenants
- checkpointing uses exactly-once settings
