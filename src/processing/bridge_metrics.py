"""Prometheus metrics for the serving bridge (S6).

The standalone bridge is not behind the API's ``/metrics`` mount
(``src/serving/api/main.py``), so it exposes its own scrape endpoint via
:func:`start_metrics_server`. The in-process bridge shares the API registry and
its counters simply show up on the API's ``/metrics``.

Health, in one line: partitions assigned **and** ``consumer_lag`` bounded or
falling **and** ``apply_failures_total`` flat **and** ``deadletter_total`` flat.
A rising lag with a flat ``applied_total`` means the bridge is stuck writing the
sink; a climbing ``apply_failures_total`` means the sink is refusing writes and
offsets are (correctly) not advancing.
"""

from __future__ import annotations

import structlog
from prometheus_client import Counter, Gauge, Histogram

logger = structlog.get_logger()

EVENTS_CONSUMED = Counter(
    "agentflow_bridge_events_consumed_total",
    "Kafka messages polled by the serving bridge.",
    labelnames=("topic",),
)

EVENTS_APPLIED = Counter(
    "agentflow_bridge_events_applied_total",
    "Events applied to the serving store by the bridge.",
)

EVENTS_DUPLICATE = Counter(
    "agentflow_bridge_events_duplicate_total",
    "Events skipped because the serving journal already carried their event_id.",
)

# Should sit at ~0: Flink validated these events before they reached
# events.validated. Sustained growth means the schema the bridge enforces has
# drifted from the one Flink enforces, or a non-canonical event type (CDC) is
# being routed to the bridge — see the S6 design, blocker F.
EVENTS_DEADLETTER = Counter(
    "agentflow_bridge_events_deadletter_total",
    "Events the bridge refused to apply, by reason.",
    labelnames=("reason",),
)

# The offset is not committed when this fires, so the batch is replayed. A
# climbing counter means the serving sink is failing, not that events are lost.
APPLY_FAILURES = Counter(
    "agentflow_bridge_apply_failures_total",
    "Batches that raised while being applied; their offsets were not committed.",
)

# The whole point of the Q1.3/Q1.4 amortization is that a batch costs a
# constant number of sink round-trips — which only pays off if batches are
# actually bigger than one. Under sustained load p50 here should sit well
# above 1; a p50 of 1 means the bridge is draining faster than events arrive
# (healthy idle) or the poll is misconfigured (batch_max too low for the lag).
APPLY_BATCH_SIZE = Histogram(
    "agentflow_bridge_apply_batch_size",
    "Events applied per non-empty batch.",
    buckets=(1, 2, 4, 8, 16, 32, 64, 128, 256, 512),
)

CONSUMER_LAG = Gauge(
    "agentflow_bridge_consumer_lag",
    "Sum over assigned partitions of (high watermark - committed offset).",
)

SECONDS_SINCE_LAST_APPLY = Gauge(
    "agentflow_bridge_seconds_since_last_apply",
    "Seconds since the bridge last applied an event (liveness).",
)


def start_metrics_server(port: int) -> None:
    """Expose the bridge's own scrape endpoint. ``port <= 0`` disables it."""
    if port <= 0:
        logger.info("bridge_metrics_server_disabled")
        return
    from prometheus_client import start_http_server

    start_http_server(port)
    logger.info("bridge_metrics_server_started", port=port)
