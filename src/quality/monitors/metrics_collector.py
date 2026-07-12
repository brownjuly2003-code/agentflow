"""Collects and exposes pipeline health metrics.

Aggregates metrics from Kafka consumer groups, Flink jobs,
and quality checks into a unified health status.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog
import yaml
from confluent_kafka import KafkaException
from prometheus_client import Gauge
from pyiceberg.exceptions import NoSuchPropertyException, RESTError, ValidationError

from src.serving.backends import BackendExecutionError

if TYPE_CHECKING:
    from src.serving.semantic_layer.journal import JournalReader

logger = structlog.get_logger()


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


PIPELINE_HEALTH = Gauge(
    "agentflow_pipeline_health",
    "Pipeline health status (1=healthy, 0.5=degraded, 0=unhealthy)",
    ["component"],
)

CONSUMER_LAG = Gauge(
    "agentflow_consumer_lag",
    "Kafka consumer group lag",
    ["group_id", "topic", "partition"],
)


class CheckSource(StrEnum):
    LIVE = "live"
    PLACEHOLDER = "placeholder"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    message: str
    last_check: datetime
    metrics: dict
    source: CheckSource = CheckSource.LIVE


@dataclass
class PipelineHealth:
    overall: HealthStatus
    components: list[ComponentHealth]
    checked_at: datetime

    def to_dict(self) -> dict:
        return {
            "status": self.overall,
            "checked_at": self.checked_at.isoformat(),
            "components": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "metrics": c.metrics,
                    "source": c.source.value,
                }
                for c in self.components
            ],
        }


class HealthCollector:
    """Aggregates health from all pipeline components.

    ``journal`` is the store the API actually serves from. Without it the
    data-plane checks report ``placeholder`` rather than inventing a store to
    read: freshness and quality used to open their own read-only DuckDB at
    ``DUCKDB_PATH``, which on the ClickHouse profile is an unrelated database
    and on the default ``:memory:`` is a brand-new empty one — so they described
    a store nobody was serving from, and never checked the one that mattered
    (audit P0-3).
    """

    def __init__(self, journal: JournalReader | None = None) -> None:
        self._journal = journal
        self._checks: list = [
            self._check_kafka,
            self._check_flink,
            self._check_serving,
            self._check_freshness,
            self._check_quality_score,
            self._check_iceberg,
        ]

    def collect(self) -> PipelineHealth:
        components = []
        for check in self._checks:
            components.append(check())

        # Overall status: worst component determines it
        statuses = [c.status for c in components]
        if HealthStatus.UNHEALTHY in statuses:
            overall = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        for c in components:
            val = {"healthy": 1.0, "degraded": 0.5, "unhealthy": 0.0}[c.status]
            PIPELINE_HEALTH.labels(component=c.name).set(val)

        return PipelineHealth(
            overall=overall,
            components=components,
            checked_at=datetime.now(UTC),
        )

    def _check_kafka(self) -> ComponentHealth:
        """Check Kafka broker connectivity and consumer lag."""
        from confluent_kafka.admin import AdminClient

        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        try:
            admin = AdminClient({"bootstrap.servers": bootstrap})
            cluster_meta = admin.list_topics(timeout=5)
        except (KafkaException, OSError) as exc:
            logger.warning(
                "kafka_check_unavailable",
                bootstrap_servers=bootstrap,
                error=str(exc),
                exc_info=True,
            )
            return ComponentHealth(
                name="kafka",
                status=HealthStatus.UNHEALTHY,
                message=f"Kafka unavailable: {exc}",
                last_check=datetime.now(UTC),
                metrics={"brokers": 0, "topics": 0},
                source=CheckSource.PLACEHOLDER,
            )
        topic_count = len(cluster_meta.topics)
        broker_count = len(cluster_meta.brokers)

        if broker_count == 0:
            return ComponentHealth(
                name="kafka",
                status=HealthStatus.UNHEALTHY,
                message="No brokers available",
                last_check=datetime.now(UTC),
                metrics={"brokers": 0},
            )

        return ComponentHealth(
            name="kafka",
            status=HealthStatus.HEALTHY,
            message=f"{broker_count} brokers, {topic_count} topics",
            last_check=datetime.now(UTC),
            metrics={"brokers": broker_count, "topics": topic_count},
        )

    def _check_flink(self) -> ComponentHealth:
        """Check Flink JobManager and running jobs."""
        flink_url = os.getenv("FLINK_JOBMANAGER_URL", "http://localhost:8081")
        try:
            resp = httpx.get(f"{flink_url}/overview", timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "flink_check_unavailable",
                flink_url=flink_url,
                error=str(exc),
                exc_info=True,
            )
            return ComponentHealth(
                name="flink",
                status=HealthStatus.UNHEALTHY,
                message=f"Flink unavailable: {exc}",
                last_check=datetime.now(UTC),
                metrics={"running_jobs": None, "failed_jobs": None},
                source=CheckSource.PLACEHOLDER,
            )

        running = data.get("jobs-running", 0)
        failed = data.get("jobs-failed", 0)

        if failed > 0:
            status = HealthStatus.DEGRADED
            msg = f"{running} running, {failed} failed"
        elif running == 0:
            status = HealthStatus.DEGRADED
            msg = "No running jobs"
        else:
            status = HealthStatus.HEALTHY
            msg = f"{running} jobs running"

        return ComponentHealth(
            name="flink",
            status=status,
            message=msg,
            last_check=datetime.now(UTC),
            metrics={"running_jobs": running, "failed_jobs": failed},
        )

    def _no_journal(self, name: str, metric_key: str) -> ComponentHealth:
        return ComponentHealth(
            name=name,
            status=HealthStatus.DEGRADED,
            message="No serving store wired into the health collector",
            last_check=datetime.now(UTC),
            metrics={metric_key: None},
            source=CheckSource.PLACEHOLDER,
        )

    def _check_serving(self) -> ComponentHealth:
        """Check the store the API actually serves from.

        There was no such check: health reported on Kafka, Flink and Iceberg,
        and read freshness and quality out of a DuckDB file it opened itself —
        so a ClickHouse deployment could have a dead serving store and a green
        /v1/health (audit P0-3).
        """
        if self._journal is None:
            return self._no_journal("serving", "backend")

        payload = self._journal.backend_health()
        status = HealthStatus.HEALTHY if payload.get("status") == "ok" else HealthStatus.UNHEALTHY
        backend = payload.get("backend", "unknown")
        message = (
            f"{backend} reachable"
            if status is HealthStatus.HEALTHY
            else f"{backend} unreachable: {payload.get('error', 'unknown error')}"
        )
        return ComponentHealth(
            name="serving",
            status=status,
            message=message,
            last_check=datetime.now(UTC),
            metrics={"backend": backend},
            source=CheckSource.LIVE,
        )

    def _check_freshness(self) -> ComponentHealth:
        """Check data freshness from the most recent pipeline event."""
        if self._journal is None:
            return self._no_journal("freshness", "last_event_age_seconds")

        # Through the active backend, against the store's own clock. This check
        # used to open its own read-only DuckDB at DUCKDB_PATH — which on the
        # ClickHouse profile is an unrelated (usually empty) store, so freshness
        # described a database nobody was writing to (audit P0-3).
        try:
            age_s = self._journal.freshness().age_seconds
        except BackendExecutionError as exc:
            logger.warning(
                "freshness_check_unavailable",
                backend=self._journal.backend_name,
                error=str(exc),
                exc_info=True,
            )
            age_s = None

        if age_s is not None:
            sla = int(os.getenv("FRESHNESS_SLA_SECONDS", "30"))
            if age_s <= sla:
                status = HealthStatus.HEALTHY
            elif age_s <= sla * 3:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.UNHEALTHY

            return ComponentHealth(
                name="freshness",
                status=status,
                message=f"Last event {age_s:.0f}s ago (SLA: {sla}s)",
                last_check=datetime.now(UTC),
                metrics={
                    "last_event_age_seconds": round(age_s, 1),
                    "sla_seconds": sla,
                },
                source=CheckSource.LIVE,
            )

        return ComponentHealth(
            name="freshness",
            status=HealthStatus.DEGRADED,
            message="No pipeline events found (run local pipeline first)",
            last_check=datetime.now(UTC),
            metrics={"last_event_age_seconds": None},
            source=CheckSource.PLACEHOLDER,
        )

    def _check_quality_score(self) -> ComponentHealth:
        """Check data quality from dead letter ratio in pipeline events."""
        if self._journal is None:
            return self._no_journal("quality", "pass_rate")

        try:
            counts = self._journal.event_counts(window="1 hour")
        except BackendExecutionError as exc:
            logger.warning(
                "quality_check_unavailable",
                backend=self._journal.backend_name,
                error=str(exc),
                exc_info=True,
            )
            counts = None

        if counts is not None and counts.total > 0:
            pass_rate = (counts.total - counts.errors) / counts.total
            if pass_rate >= 0.99:
                status = HealthStatus.HEALTHY
            elif pass_rate >= 0.95:
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.UNHEALTHY

            return ComponentHealth(
                name="quality",
                status=status,
                message=f"Pass rate: {pass_rate:.1%} ({counts.errors}/{counts.total} rejected)",
                last_check=datetime.now(UTC),
                metrics={
                    "pass_rate": round(pass_rate, 4),
                    "total_events": counts.total,
                    "rejected_events": counts.errors,
                },
                source=CheckSource.LIVE,
            )

        return ComponentHealth(
            name="quality",
            status=HealthStatus.DEGRADED,
            message="No pipeline events found (run local pipeline first)",
            last_check=datetime.now(UTC),
            metrics={"pass_rate": None},
            source=CheckSource.PLACEHOLDER,
        )

    def _check_iceberg(self) -> ComponentHealth:
        """Check Iceberg catalog accessibility and row counts."""
        config_path = Path(os.getenv("AGENTFLOW_ICEBERG_CONFIG", "config/iceberg.yaml"))
        if not config_path.exists():
            return ComponentHealth(
                name="iceberg",
                status=HealthStatus.DEGRADED,
                message="Iceberg config not found",
                last_check=datetime.now(UTC),
                metrics={"row_counts": {}},
                source=CheckSource.PLACEHOLDER,
            )

        try:
            from src.processing.iceberg_sink import IcebergSink

            sink = IcebergSink(config_path=config_path)
            row_counts = sink.row_counts()
        except (
            ImportError,
            OSError,
            KeyError,
            ValueError,
            yaml.YAMLError,
            NoSuchPropertyException,
            RESTError,
            ValidationError,
        ) as exc:
            logger.warning(
                "iceberg_check_unavailable",
                config_path=str(config_path),
                error=str(exc),
                exc_info=True,
            )
            return ComponentHealth(
                name="iceberg",
                status=HealthStatus.DEGRADED,
                message=f"Iceberg unavailable: {exc}",
                last_check=datetime.now(UTC),
                metrics={"row_counts": {}},
                source=CheckSource.PLACEHOLDER,
            )

        total_rows = sum(row_counts.values())
        return ComponentHealth(
            name="iceberg",
            status=HealthStatus.HEALTHY,
            message=f"{len(row_counts)} tables, {total_rows} rows",
            last_check=datetime.now(UTC),
            metrics={
                "row_counts": row_counts,
                "total_rows": total_rows,
            },
            source=CheckSource.LIVE,
        )
