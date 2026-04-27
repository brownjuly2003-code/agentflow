"""Local pipeline: end-to-end data flow without Kafka or Flink.

Generates → validates → enriches → writes to DuckDB in real-time.
Proves the pipeline works end-to-end, locally, with zero infrastructure.

Usage:
    python -m src.processing.local_pipeline                # default: 10 events/sec
    python -m src.processing.local_pipeline --eps 50       # 50 events/sec
    python -m src.processing.local_pipeline --burst 500    # one-shot: 500 events
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import structlog
import yaml  # type: ignore[import-untyped]
from pyiceberg.exceptions import NoSuchPropertyException, RESTError, ValidationError

from src.ingestion.producers.event_producer import (
    generate_click,
    generate_order,
    generate_payment,
    generate_product,
)
from src.logger import configure_logging
from src.processing.iceberg_sink import IcebergSink
from src.processing.transformations.enrichment import (
    compute_payment_risk_score,
    enrich_clickstream,
    enrich_order,
)
from src.quality.validators.schema_validator import validate_event
from src.quality.validators.semantic_validator import validate_semantics

DB_PATH = os.getenv("DUCKDB_PATH", "agentflow_demo.duckdb")


def _ensure_tables(conn: duckdb.DuckDBPyConnection):
    """Create all tables if they don't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders_v2 (
            order_id VARCHAR PRIMARY KEY,
            user_id VARCHAR,
            status VARCHAR,
            total_amount DECIMAL(10,2),
            currency VARCHAR DEFAULT 'USD',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products_current (
            product_id VARCHAR PRIMARY KEY,
            name VARCHAR,
            category VARCHAR,
            price DECIMAL(10,2),
            in_stock BOOLEAN DEFAULT TRUE,
            stock_quantity INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions_aggregated (
            session_id VARCHAR PRIMARY KEY,
            user_id VARCHAR,
            started_at TIMESTAMP,
            ended_at TIMESTAMP,
            duration_seconds FLOAT,
            event_count INTEGER,
            unique_pages INTEGER,
            funnel_stage VARCHAR,
            is_conversion BOOLEAN DEFAULT FALSE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users_enriched (
            user_id VARCHAR PRIMARY KEY,
            total_orders INTEGER DEFAULT 0,
            total_spent DECIMAL(10,2) DEFAULT 0,
            first_order_at TIMESTAMP,
            last_order_at TIMESTAMP,
            preferred_category VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_events (
            event_id VARCHAR,
            topic VARCHAR,
            tenant_id VARCHAR DEFAULT 'default',
            event_type VARCHAR,
            latency_ms INTEGER,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS tenant_id VARCHAR DEFAULT 'default'"
    )


def _event_tenant(event: dict) -> str:
    source_metadata = event.get("source_metadata", {})
    metadata_tenant = (
        source_metadata.get("tenant") if isinstance(source_metadata, dict) else None
    )
    tenant = event.get("tenant") or metadata_tenant
    return str(tenant) if tenant else "default"


def _process_event(
    conn: duckdb.DuckDBPyConnection,
    event: dict,
    iceberg_sink: IcebergSink | None = None,
) -> tuple[bool, str]:
    """Validate, enrich, and store a single event. Returns (success, reason)."""
    event_type = event.get("event_type", "")
    event_id = event.get("event_id", "unknown")
    tenant_id = _event_tenant(event)

    conn.execute("BEGIN")
    try:
        # Schema validation
        schema_result = validate_event(event)
        if not schema_result.is_valid:
            conn.execute(
                """
                INSERT INTO pipeline_events (
                    event_id, topic, tenant_id, event_type, latency_ms, processed_at
                )
                VALUES (?, 'events.deadletter', ?, ?, 0, ?)
                """,
                [event_id, tenant_id, event_type, datetime.now(UTC)],
            )
            if iceberg_sink is not None:
                iceberg_sink.write_batch(
                    "dead_letter",
                    [
                        {
                            "event_id": event.get("event_id"),
                            "event_type": event.get("event_type"),
                            "reason": f"schema: {schema_result.errors[0]}",
                            "source_topic": "events.deadletter",
                            "received_at": datetime.now(UTC),
                            "payload": event,
                        }
                    ],
                )
            conn.execute("COMMIT")
            return False, f"schema: {schema_result.errors[0]}"

        # Semantic validation
        semantic_result = validate_semantics(event)
        error_issues = [i for i in semantic_result.issues if i.severity == "error"]
        if error_issues:
            conn.execute(
                """
                INSERT INTO pipeline_events (
                    event_id, topic, tenant_id, event_type, latency_ms, processed_at
                )
                VALUES (?, 'events.deadletter', ?, ?, 0, ?)
                """,
                [event_id, tenant_id, event_type, datetime.now(UTC)],
            )
            if iceberg_sink is not None:
                iceberg_sink.write_batch(
                    "dead_letter",
                    [
                        {
                            "event_id": event.get("event_id"),
                            "event_type": event.get("event_type"),
                            "reason": f"semantic: {error_issues[0].rule}",
                            "source_topic": "events.deadletter",
                            "received_at": datetime.now(UTC),
                            "payload": event,
                        }
                    ],
                )
            conn.execute("COMMIT")
            return False, f"semantic: {error_issues[0].rule}"

        # Enrichment
        if event_type.startswith("order."):
            event = enrich_order(event)
            _upsert_order(conn, event)
            if iceberg_sink is not None:
                iceberg_sink.write_batch("orders", [event])
        elif event_type in ("click", "page_view", "add_to_cart"):
            event = enrich_clickstream(event)
            _upsert_session(conn, event)
            if iceberg_sink is not None:
                iceberg_sink.write_batch("clickstream", [event])
        elif event_type.startswith("payment."):
            event = compute_payment_risk_score(event)
            if iceberg_sink is not None:
                iceberg_sink.write_batch("payments", [event])
        elif event_type.startswith("product."):
            _upsert_product(conn, event)
            if iceberg_sink is not None:
                iceberg_sink.write_batch("inventory", [event])

        # Record in pipeline_events
        ts = event.get("timestamp", "")
        try:
            event_ts = datetime.fromisoformat(ts)
            if event_ts.tzinfo is None:
                event_ts = event_ts.replace(tzinfo=UTC)
            latency_ms = int((datetime.now(UTC) - event_ts).total_seconds() * 1000)
        except (ValueError, TypeError):
            latency_ms = 0

        conn.execute(
            """
            INSERT INTO pipeline_events (
                event_id, topic, tenant_id, event_type, latency_ms, processed_at
            )
            VALUES (?, 'events.validated', ?, ?, ?, ?)
            """,
            [event_id, tenant_id, event_type, latency_ms, datetime.now(UTC)],
        )
        conn.execute("COMMIT")
        return True, "ok"
    except Exception:  # nosec B110 - rollback must preserve the original pipeline failure
        # Transaction rollback must happen before unexpected errors propagate.
        conn.execute("ROLLBACK")
        raise


def _upsert_order(conn: duckdb.DuckDBPyConnection, event: dict):
    conn.execute(
        """
        INSERT OR REPLACE INTO orders_v2
        (order_id, user_id, status, total_amount, currency, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        [
            event["order_id"],
            event["user_id"],
            event["status"],
            float(event["total_amount"]),
            event.get("currency", "USD"),
            datetime.fromisoformat(event["timestamp"]),
        ],
    )
    # Update user aggregate
    conn.execute(
        """
        INSERT OR REPLACE INTO users_enriched
        (user_id, total_orders, total_spent,
         first_order_at, last_order_at, preferred_category)
        SELECT
            user_id,
            COUNT(*) as total_orders,
            SUM(total_amount) as total_spent,
            MIN(created_at),
            MAX(created_at),
            NULL
        FROM orders_v2
        WHERE user_id = ? AND status != 'cancelled'
        GROUP BY user_id
    """,
        [event["user_id"]],
    )


def _upsert_product(conn: duckdb.DuckDBPyConnection, event: dict):
    conn.execute(
        """
        INSERT OR REPLACE INTO products_current
        (product_id, name, category, price, in_stock, stock_quantity)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        [
            event["product_id"],
            event["name"],
            event["category"],
            float(event["price"]),
            event["in_stock"],
            event["stock_quantity"],
        ],
    )


def _upsert_session(conn: duckdb.DuckDBPyConnection, event: dict):
    session_id = event.get("session_id", "unknown")
    derived = event.get("_derived", {})
    page_cat = derived.get("page_category", "other")

    # Determine funnel stage from page category
    stage_order = {
        "checkout": 4,
        "cart": 3,
        "product_detail": 2,
        "search": 1,
        "home": 0,
        "other": 0,
    }
    new_stage_val = stage_order.get(page_cat, 0)

    existing = conn.execute(
        "SELECT funnel_stage, event_count FROM sessions_aggregated WHERE session_id = ?",
        [session_id],
    ).fetchone()

    if existing:
        old_stage = existing[0] or "bounce"
        old_count = existing[1] or 0
        old_stage_val = stage_order.get(old_stage, 0)
        funnel = page_cat if new_stage_val > old_stage_val else old_stage
        conn.execute(
            """
            UPDATE sessions_aggregated
            SET event_count = ?,
                funnel_stage = ?,
                is_conversion = ?
            WHERE session_id = ?
        """,
            [
                old_count + 1,
                funnel,
                funnel == "checkout",
                session_id,
            ],
        )
    else:
        conn.execute(
            """
            INSERT INTO sessions_aggregated
            (session_id, user_id, started_at, ended_at,
             duration_seconds, event_count, unique_pages,
             funnel_stage, is_conversion)
            VALUES (?, ?, ?, NULL, 0, 1, 1, ?, ?)
        """,
            [
                session_id,
                event.get("user_id"),
                datetime.now(UTC),
                page_cat,
                page_cat == "checkout",
            ],
        )


def _generate_random_event() -> tuple[str, dict]:
    """Generate a random event using existing producers."""
    import random

    generators: list[tuple] = [
        (0.15, generate_order),
        (0.25, generate_payment),
        (0.95, generate_click),
        (1.00, generate_product),
    ]
    roll = random.random()
    for threshold, gen in generators:
        if roll < threshold:
            topic, event = gen()
            return topic, json.loads(event.model_dump_json())
    topic, event = generate_product()
    return topic, json.loads(event.model_dump_json())


def run(events_per_second: int = 10, burst: int = 0):
    """Run the local pipeline."""
    configure_logging()
    logger = structlog.get_logger()
    conn = duckdb.connect(DB_PATH)
    _ensure_tables(conn)
    iceberg_sink = None
    iceberg_config = os.getenv("AGENTFLOW_ICEBERG_CONFIG")
    if not iceberg_config:
        default_iceberg_config = Path("config/iceberg.yaml")
        if default_iceberg_config.exists():
            iceberg_config = str(default_iceberg_config)
    if iceberg_config:
        try:
            iceberg_sink = IcebergSink(config_path=iceberg_config)
            iceberg_sink.create_tables_if_not_exist()
        except (
            OSError,
            KeyError,
            ValueError,
            yaml.YAMLError,
            NoSuchPropertyException,
            RESTError,
            ValidationError,
        ) as exc:
            iceberg_sink = None
            logger.warning(
                "iceberg_sink_unavailable",
                config=iceberg_config,
                error=str(exc),
                exc_info=True,
            )

    logger.info(
        "local_pipeline_started",
        db=DB_PATH,
        eps=events_per_second,
        burst=burst,
    )

    total = 0
    valid = 0
    invalid = 0
    start_time = time.monotonic()

    try:
        count = burst if burst > 0 else float("inf")
        while total < count:
            _, event = _generate_random_event()
            success, reason = _process_event(conn, event, iceberg_sink=iceberg_sink)

            total += 1
            if success:
                valid += 1
            else:
                invalid += 1

            if total % 100 == 0:
                elapsed = time.monotonic() - start_time
                logger.info(
                    "pipeline_progress",
                    total=total,
                    valid=valid,
                    invalid=invalid,
                    rate=f"{total / elapsed:.0f} evt/s",
                )

            if burst == 0:
                time.sleep(1.0 / events_per_second)

    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.monotonic() - start_time
        conn.close()
        logger.info(
            "local_pipeline_stopped",
            total=total,
            valid=valid,
            invalid=invalid,
            duration_s=round(elapsed, 1),
            avg_rate=f"{total / max(elapsed, 0.001):.0f} evt/s",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentFlow local pipeline")
    parser.add_argument("--eps", type=int, default=10, help="Events per second")
    parser.add_argument("--burst", type=int, default=0, help="One-shot: N events then stop")
    args = parser.parse_args()
    run(events_per_second=args.eps, burst=args.burst)
