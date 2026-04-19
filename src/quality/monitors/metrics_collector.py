"""Collects and exposes pipeline health metrics.

Aggregates metrics from Kafka consumer groups, Flink jobs,
and quality checks into a unified health status.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import duckdb
import httpx
import structlog
import yaml  # type: ignore[import-untyped]
from confluent_kafka import KafkaException
from prometheus_client import Gauge
from pyiceberg.exceptions import NoSuchPropertyException, RESTError, ValidationError

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
    """Aggregates health from all pipeline components."""

    def __init__(self):
        self._checks: list = [
            self._check_kafka,
            self._check_flink,
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

    def _check_freshness(self) -> ComponentHealth:
        """Check data freshness from the most recent pipeline event."""
        try:
            db_path = os.getenv("DUCKDB_PATH", "agentflow_demo.duckdb")
            conn = duckdb.connect(db_path, read_only=True)
            row = conn.execute(
                "SELECT MAX(processed_at) FROM pipeline_events"
            ).fetchone()
            conn.close()

            if row and row[0]:
                last_event = row[0]
                if hasattr(last_event, "timestamp"):
                    age_s = (
                        datetime.now(UTC) - last_event.replace(tzinfo=UTC)
                    ).total_seconds()
                else:
                    age_s = -1.0

                sla = int(os.getenv("FRESHNESS_SLA_SECONDS", "30"))
                if age_s <= sla:
                    status = HealthStatus.HEALTHY
                    msg = f"Last event {age_s:.0f}s ago (SLA: {sla}s)"
                elif age_s <= sla * 3:
                    status = HealthStatus.DEGRADED
                    msg = f"Last event {age_s:.0f}s ago (SLA: {sla}s)"
                else:
                    status = HealthStatus.UNHEALTHY
                    msg = f"Last event {age_s:.0f}s ago (SLA: {sla}s)"

                return ComponentHealth(
                    name="freshness",
                    status=status,
                    message=msg,
                    last_check=datetime.now(UTC),
                    metrics={
                        "last_event_age_seconds": round(age_s, 1),
                        "sla_seconds": sla,
                    },
                    source=CheckSource.LIVE,
                )
        except duckdb.Error as exc:
            logger.warning(
                "freshness_check_unavailable",
                db_path=db_path,
                error=str(exc),
                exc_info=True,
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
        try:
            db_path = os.getenv("DUCKDB_PATH", "agentflow_demo.duckdb")
            conn = duckdb.connect(db_path, read_only=True)
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (
                        WHERE topic = 'events.deadletter'
                    ) as dead
                FROM pipeline_events
                WHERE processed_at >= NOW() - INTERVAL '1 hour'
            """).fetchone()
            conn.close()

            if row and row[0] and row[0] > 0:
                total, dead = row[0], row[1]
                pass_rate = (total - dead) / total
                if pass_rate >= 0.99:
                    status = HealthStatus.HEALTHY
                elif pass_rate >= 0.95:
                    status = HealthStatus.DEGRADED
                else:
                    status = HealthStatus.UNHEALTHY

                return ComponentHealth(
                    name="quality",
                    status=status,
                    message=f"Pass rate: {pass_rate:.1%} ({dead}/{total} rejected)",
                    last_check=datetime.now(UTC),
                    metrics={
                        "pass_rate": round(pass_rate, 4),
                        "total_events": total,
                        "rejected_events": dead,
                    },
                    source=CheckSource.LIVE,
                )
        except duckdb.Error as exc:
            logger.warning(
                "quality_check_unavailable",
                db_path=db_path,
                error=str(exc),
                exc_info=True,
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
