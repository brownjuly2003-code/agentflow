"""Monitors data freshness across all pipeline stages.

Checks that events flow through the pipeline within SLA bounds.
Exposes metrics to Prometheus and triggers alerts on SLA breaches.

SLA: end-to-end latency (ingestion → serving) < 30 seconds for p99.
"""

import json
import os
from collections import defaultdict
from datetime import UTC, datetime

import structlog
from confluent_kafka import Consumer, KafkaError
from prometheus_client import Gauge, Histogram, start_http_server

logger = structlog.get_logger()

FRESHNESS_SLA_SECONDS = int(os.getenv("FRESHNESS_SLA_SECONDS", "30"))

# Prometheus metrics
PIPELINE_LATENCY = Histogram(
    "agentflow_pipeline_latency_seconds",
    "End-to-end pipeline latency in seconds",
    ["topic", "event_type"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

SLA_COMPLIANCE = Gauge(
    "agentflow_sla_compliance_ratio",
    "Ratio of events within SLA (rolling 5-min window)",
    ["topic"],
)

EVENTS_PROCESSED = Gauge(
    "agentflow_freshness_events_total",
    "Total events checked by freshness monitor",
    ["topic"],
)


class FreshnessMonitor:
    """Consumes from validated topics and measures pipeline latency."""

    def __init__(self, bootstrap_servers: str, topics: list[str]):
        self.consumer = Consumer({
            "bootstrap.servers": bootstrap_servers,
            "group.id": "agentflow-freshness-monitor",
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        })
        self.topics = topics
        self._sla_window: dict[str, list[bool]] = defaultdict(list)
        self._window_size = 1000  # last N events per topic

    def start(self, metrics_port: int = 8001):
        """Start monitoring loop with Prometheus metrics endpoint."""
        start_http_server(metrics_port)
        logger.info("freshness_monitor_started", topics=self.topics, port=metrics_port)

        self.consumer.subscribe(self.topics)

        try:
            while True:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        logger.error("kafka_error", error=str(msg.error()))
                    continue

                self._process_message(msg)
        except KeyboardInterrupt:
            logger.info("freshness_monitor_stopping")
        finally:
            self.consumer.close()

    def _process_message(self, msg):
        topic = msg.topic()
        try:
            event = json.loads(msg.value().decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        # Calculate latency from event timestamp to now
        event_ts_str = event.get("timestamp")
        if not event_ts_str:
            return

        try:
            event_ts = datetime.fromisoformat(event_ts_str)
            if event_ts.tzinfo is None:
                event_ts = event_ts.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            latency = (now - event_ts).total_seconds()
        except (ValueError, TypeError):
            return

        event_type = event.get("event_type", "unknown")

        # Record metrics
        PIPELINE_LATENCY.labels(topic=topic, event_type=event_type).observe(latency)
        EVENTS_PROCESSED.labels(topic=topic).inc()

        # Track SLA compliance
        within_sla = latency <= FRESHNESS_SLA_SECONDS
        window = self._sla_window[topic]
        window.append(within_sla)
        if len(window) > self._window_size:
            window.pop(0)

        compliance = sum(window) / len(window)
        SLA_COMPLIANCE.labels(topic=topic).set(compliance)

        if not within_sla:
            logger.warning(
                "sla_breach",
                topic=topic,
                event_type=event_type,
                latency_seconds=round(latency, 2),
                sla_seconds=FRESHNESS_SLA_SECONDS,
                event_id=event.get("event_id"),
            )


if __name__ == "__main__":
    monitor = FreshnessMonitor(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        topics=["events.validated", "sessions.aggregated"],
    )
    monitor.start()
