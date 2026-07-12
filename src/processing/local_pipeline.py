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
import yaml
from pyiceberg.exceptions import NoSuchPropertyException, RESTError, ValidationError

from src.ingestion.producers.event_producer import (
    generate_click,
    generate_order,
    generate_payment,
    generate_product,
)
from src.logger import configure_logging
from src.processing.clickhouse_sink import ClickHouseSink
from src.processing.event_tenant import event_tenant
from src.processing.iceberg_sink import IcebergSink
from src.processing.transformations.enrichment import (
    compute_payment_risk_score,
    enrich_clickstream,
    enrich_order,
)
from src.quality.validators.schema_validator import validate_event
from src.quality.validators.semantic_validator import validate_semantics
from src.serving.backends.duckdb_backend import DuckDBBackend

DB_PATH = os.getenv("DUCKDB_PATH", "agentflow_demo.duckdb")


def _ensure_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the tables this pipeline writes, if they don't exist.

    One DDL for the whole DuckDB store: ``DuckDBBackend.ensure_schema`` owns it,
    and this used to keep a second, hand-maintained copy of the same five tables.
    They had already drifted (the copy's ``pipeline_events`` was missing columns
    the other one declared, and only got them back through ALTERs), and the
    tenant key — the boundary itself (ADR-004) — is exactly the kind of thing a
    second copy silently omits. So there is no second copy.
    """
    DuckDBBackend(db_path=DB_PATH, connection=conn).ensure_schema()


def _event_tenant(event: dict) -> str:
    # Shared with the ClickHouse sink, which stamps the same tenant onto the
    # serving rows it writes (P0-1) and cannot import this module.
    return event_tenant(event)


def _event_branch(event: dict) -> str | None:
    """Originating branch of a federated event (ADR 0012 N4).

    The center's node-ingest endpoint stamps ``source_metadata.branch`` with the
    edge's ``origin_branch`` before applying, so the ``pipeline_events`` journal
    carries branch attribution. In-process events (standalone/edge local
    generator) leave it ``NULL`` — never synthesized."""
    source_metadata = event.get("source_metadata", {})
    branch = source_metadata.get("branch") if isinstance(source_metadata, dict) else None
    return str(branch) if branch else None


# ops-surfaces-spec.md §1.3: the entity_id axis of the pipeline_events journal
# is what Order 360 (and lineage) key off of. NULL when the id isn't
# derivable from the payload — never synthesized.
_ENTITY_ID_FIELD_BY_PREFIX = (
    ("order.", "order_id"),
    ("user.", "user_id"),
    ("product.", "product_id"),
    ("session.", "session_id"),
)


def _derive_entity_id(event: dict, event_type: str) -> str | None:
    for prefix, field_name in _ENTITY_ID_FIELD_BY_PREFIX:
        if event_type.startswith(prefix):
            value = event.get(field_name)
            return str(value) if value is not None else None
    return None


def _process_event(
    conn: duckdb.DuckDBPyConnection,
    event: dict,
    iceberg_sink: IcebergSink | None = None,
    clickhouse_sink: ClickHouseSink | None = None,
    *,
    skip_local_store: bool = False,
) -> tuple[bool, str]:
    """Validate, enrich, and store a single event. Returns (success, reason).

    ``skip_local_store=True`` is the ClickHouse bridge path (Q1.2): the serving
    store is the only durable writer, so the per-event DuckDB BEGIN/COMMIT on a
    throwaway scratch lake is pure ceiling (~8 eps on S10). Validation and
    enrichment still run in-process; journal + entity writes go only to
    ``clickhouse_sink``. Requires ``clickhouse_sink is not None``.
    """
    if skip_local_store:
        if clickhouse_sink is None:
            raise ValueError("skip_local_store requires clickhouse_sink")
        return _process_event_serving_only(event, clickhouse_sink)

    event_type = event.get("event_type", "")
    event_id = event.get("event_id", "unknown")
    tenant_id = _event_tenant(event)
    entity_id = _derive_entity_id(event, event_type)
    branch = _event_branch(event)

    conn.execute("BEGIN")
    try:
        # Schema validation
        schema_result = validate_event(event)
        if not schema_result.is_valid:
            conn.execute(
                """
                INSERT INTO pipeline_events (
                    event_id, topic, tenant_id, entity_id, event_type, latency_ms,
                    processed_at, branch
                )
                VALUES (?, 'events.deadletter', ?, ?, ?, 0, ?, ?)
                """,
                [event_id, tenant_id, entity_id, event_type, datetime.now(UTC), branch],
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
            # Mirror to the ClickHouse serving store only after the DuckDB
            # commit, so a serving-store failure never rolls back or forks the
            # local lake state; the mirror raising is deliberate (loud) —
            # see ClickHouseSink.from_serving_config.
            if clickhouse_sink is not None:
                clickhouse_sink.record_pipeline_event(
                    event_id=str(event_id),
                    topic="events.deadletter",
                    tenant_id=tenant_id,
                    entity_id=entity_id,
                    event_type=event_type,
                    latency_ms=0,
                )
            return False, f"schema: {schema_result.errors[0]}"

        # Semantic validation
        semantic_result = validate_semantics(event)
        error_issues = [i for i in semantic_result.issues if i.severity == "error"]
        if error_issues:
            conn.execute(
                """
                INSERT INTO pipeline_events (
                    event_id, topic, tenant_id, entity_id, event_type, latency_ms,
                    processed_at, branch
                )
                VALUES (?, 'events.deadletter', ?, ?, ?, 0, ?, ?)
                """,
                [event_id, tenant_id, entity_id, event_type, datetime.now(UTC), branch],
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
            if clickhouse_sink is not None:
                clickhouse_sink.record_pipeline_event(
                    event_id=str(event_id),
                    topic="events.deadletter",
                    tenant_id=tenant_id,
                    entity_id=entity_id,
                    event_type=event_type,
                    latency_ms=0,
                )
            return False, f"semantic: {error_issues[0].rule}"

        # Enrichment
        if event_type.startswith("order."):
            event = enrich_order(event)
            _upsert_order(conn, event)
            _record_order_status(conn, event, event_id, tenant_id, branch)
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
                event_id, topic, tenant_id, entity_id, event_type, latency_ms,
                processed_at, branch
            )
            VALUES (?, 'events.validated', ?, ?, ?, ?, ?, ?)
            """,
            [event_id, tenant_id, entity_id, event_type, latency_ms, datetime.now(UTC), branch],
        )
        conn.execute("COMMIT")
        if clickhouse_sink is not None:
            if event_type.startswith("order."):
                clickhouse_sink.upsert_order(event)
                clickhouse_sink.record_pipeline_event(
                    event_id=f"{event_id}-status",
                    topic="orders.status",
                    tenant_id=tenant_id,
                    entity_id=str(event["order_id"]),
                    event_type=f"order.status.{event['status']}",
                    latency_ms=None,
                    processed_at=datetime.now(UTC),
                )
            elif event_type in ("click", "page_view", "add_to_cart"):
                clickhouse_sink.upsert_session(event)
            elif event_type.startswith("product."):
                clickhouse_sink.upsert_product(event)
            clickhouse_sink.record_pipeline_event(
                event_id=str(event_id),
                topic="events.validated",
                tenant_id=tenant_id,
                entity_id=entity_id,
                event_type=event_type,
                latency_ms=latency_ms,
            )
        return True, "ok"
    # rollback must preserve the original pipeline failure
    except Exception:  # nosec B110
        # Transaction rollback must happen before unexpected errors propagate.
        conn.execute("ROLLBACK")
        raise


def _process_event_serving_only(
    event: dict,
    clickhouse_sink: ClickHouseSink,
) -> tuple[bool, str]:
    """Apply one event to ClickHouse only (no DuckDB). Thin wrapper on batch."""
    results = apply_serving_batch([event], clickhouse_sink)
    _, success, reason = results[0]
    return success, reason


def apply_serving_batch(
    events: list[dict],
    clickhouse_sink: ClickHouseSink,
) -> list[tuple[str, bool, str]]:
    """Batch-apply events to **ClickHouse only** (Q1.3 / production bridge path).

    No DuckDB. Production serving store is ClickHouse; the dual-write demo path
    still uses :func:`_process_event` with a lake connection for local tests.

    Per batch this issues a *constant* number of ClickHouse round-trips (Q1.4),
    independent of batch size:
    - one multi-row ``orders_v2`` insert (all successful orders)
    - one multi-row ``products_current`` insert
    - one batched session fold: one SELECT over the batch's session ids + one
      multi-row versions insert (was: SELECT + INSERT per clickstream event)
    - one batched ``users_enriched`` recompute: one grouped SELECT over the
      batch's user ids + one multi-row insert (was: SELECT + INSERT per user)
    - one multi-row ``pipeline_events`` journal insert

    Returns ``(event_id, success, reason)`` in input order. Schema/semantic
    rejects are dead-lettered into the journal and counted as failures without
    raising; hard CH errors raise so the bridge can rewind Kafka offsets.
    """
    if not events:
        return []

    results: list[tuple[str, bool, str]] = []
    order_events: list[dict] = []
    product_events: list[dict] = []
    session_events: list[dict] = []
    journal_rows: list[dict] = []
    # (tenant, user): a user id is only unique within a tenant, so the aggregate
    # recompute has to be keyed by both (audit P0-1).
    pending_users: set[tuple[str, str]] = set()
    now = datetime.now(UTC)

    for event in events:
        event_type = event.get("event_type", "")
        event_id = str(event.get("event_id", "unknown"))
        tenant_id = _event_tenant(event)
        entity_id = _derive_entity_id(event, event_type)

        schema_result = validate_event(event)
        if not schema_result.is_valid:
            journal_rows.append(
                {
                    "event_id": event_id,
                    "topic": "events.deadletter",
                    "tenant_id": tenant_id,
                    "entity_id": entity_id,
                    "event_type": event_type,
                    "latency_ms": 0,
                    "processed_at": now,
                }
            )
            results.append((event_id, False, f"schema: {schema_result.errors[0]}"))
            continue

        semantic_result = validate_semantics(event)
        error_issues = [i for i in semantic_result.issues if i.severity == "error"]
        if error_issues:
            journal_rows.append(
                {
                    "event_id": event_id,
                    "topic": "events.deadletter",
                    "tenant_id": tenant_id,
                    "entity_id": entity_id,
                    "event_type": event_type,
                    "latency_ms": 0,
                    "processed_at": now,
                }
            )
            results.append((event_id, False, f"semantic: {error_issues[0].rule}"))
            continue

        working = event
        if event_type.startswith("order."):
            working = enrich_order(event)
            order_events.append(working)
            pending_users.add((tenant_id, str(working["user_id"])))
            journal_rows.append(
                {
                    "event_id": f"{event_id}-status",
                    "topic": "orders.status",
                    "tenant_id": tenant_id,
                    "entity_id": str(working["order_id"]),
                    "event_type": f"order.status.{working['status']}",
                    "latency_ms": None,
                    "processed_at": now,
                }
            )
            entity_id = str(working["order_id"])
        elif event_type in ("click", "page_view", "add_to_cart"):
            working = enrich_clickstream(event)
            session_events.append(working)
        elif event_type.startswith("payment."):
            working = compute_payment_risk_score(event)
        elif event_type.startswith("product."):
            product_events.append(working)

        ts = working.get("timestamp", "")
        try:
            event_ts = datetime.fromisoformat(ts)
            if event_ts.tzinfo is None:
                event_ts = event_ts.replace(tzinfo=UTC)
            latency_ms = int((datetime.now(UTC) - event_ts).total_seconds() * 1000)
        except (ValueError, TypeError):
            latency_ms = 0

        journal_rows.append(
            {
                "event_id": event_id,
                "topic": "events.validated",
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "event_type": event_type,
                "latency_ms": latency_ms,
                "processed_at": now,
            }
        )
        results.append((event_id, True, "ok"))

    # Durable writes — all ClickHouse (no DuckDB). Journal last so a crash
    # mid-batch leaves events replayable (idempotency guard has not seen them).
    clickhouse_sink.insert_orders(order_events)
    clickhouse_sink.insert_products(product_events)
    clickhouse_sink.upsert_sessions(session_events)
    clickhouse_sink.refresh_user_aggregates(pending_users)
    clickhouse_sink.record_pipeline_events(journal_rows)
    return results


def _upsert_order(conn: duckdb.DuckDBPyConnection, event: dict) -> None:
    tenant_id = _event_tenant(event)
    conn.execute(
        """
        INSERT OR REPLACE INTO orders_v2
        (tenant_id, order_id, user_id, status, total_amount, currency, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        [
            tenant_id,
            event["order_id"],
            event["user_id"],
            event["status"],
            float(event["total_amount"]),
            event.get("currency", "RUB"),
            datetime.fromisoformat(event["timestamp"]),
        ],
    )
    # Update user aggregate. Scoped and grouped by tenant: a user id is unique
    # only within a tenant, so a global GROUP BY user_id would sum two tenants'
    # orders into one total and write it back to both (audit P0-1).
    conn.execute(
        """
        INSERT OR REPLACE INTO users_enriched
        (tenant_id, user_id, total_orders, total_spent,
         first_order_at, last_order_at, preferred_category)
        SELECT
            tenant_id,
            user_id,
            COUNT(*) as total_orders,
            SUM(total_amount) as total_spent,
            MIN(created_at),
            MAX(created_at),
            NULL
        FROM orders_v2
        WHERE tenant_id = ? AND user_id = ? AND status != 'cancelled'
        GROUP BY tenant_id, user_id
    """,
        [tenant_id, event["user_id"]],
    )


def _record_order_status(
    conn: duckdb.DuckDBPyConnection,
    event: dict,
    event_id: str,
    tenant_id: str,
    branch: str | None = None,
) -> None:
    """Stage-entry journal row (ops-surfaces-spec.md §1.2) — the stage clock
    for Order 360 / stuck-orders. ``topic='orders.status'`` is deliberately
    disjoint from the ingestion vocabulary (``order.created``, ...) so it
    never gets picked up by scans that filter on ingestion event types."""
    conn.execute(
        """
        INSERT INTO pipeline_events (
            event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at, branch
        )
        VALUES (?, 'orders.status', ?, ?, ?, NULL, ?, ?)
        """,
        [
            f"{event_id}-status",
            tenant_id,
            str(event["order_id"]),
            f"order.status.{event['status']}",
            datetime.now(UTC),
            branch,
        ],
    )


def _upsert_product(conn: duckdb.DuckDBPyConnection, event: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO products_current
        (tenant_id, product_id, name, category, price, in_stock, stock_quantity)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        [
            _event_tenant(event),
            event["product_id"],
            event["name"],
            event["category"],
            float(event["price"]),
            event["in_stock"],
            event["stock_quantity"],
        ],
    )


def _upsert_session(conn: duckdb.DuckDBPyConnection, event: dict) -> None:
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

    # A session id is unique only within a tenant, so both the lookup and the
    # update are keyed by (tenant, session) — otherwise one tenant's clickstream
    # folds into another's session (audit P0-1).
    tenant_id = _event_tenant(event)
    existing = conn.execute(
        "SELECT funnel_stage, event_count FROM sessions_aggregated "
        "WHERE tenant_id = ? AND session_id = ?",
        [tenant_id, session_id],
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
            WHERE tenant_id = ? AND session_id = ?
        """,
            [
                old_count + 1,
                funnel,
                funnel == "checkout",
                tenant_id,
                session_id,
            ],
        )
    else:
        conn.execute(
            """
            INSERT INTO sessions_aggregated
            (tenant_id, session_id, user_id, started_at, ended_at,
             duration_seconds, event_count, unique_pages,
             funnel_stage, is_conversion)
            VALUES (?, ?, ?, ?, NULL, 0, 1, 1, ?, ?)
        """,
            [
                tenant_id,
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


def _format_rate(total: float, elapsed: float) -> str:
    # Guard against a zero elapsed window: on coarse-resolution monotonic clocks
    # (e.g. Windows) the first 100-event progress tick of a --burst run can land
    # within a single clock tick (elapsed == 0.0), which would raise
    # ZeroDivisionError in the progress log. (audit_28_06_26.md §5 low)
    return f"{total / max(elapsed, 0.001):.0f} evt/s"


def run(events_per_second: int = 10, burst: int = 0) -> None:
    """Run the local pipeline."""
    configure_logging()
    logger = structlog.get_logger()
    conn = duckdb.connect(DB_PATH)
    _ensure_tables(conn)
    # ADR 0006: when serving is ClickHouse, mirror serving-table writes there
    # so the store the API reads is the one that moves when events happen.
    # A configured-but-unreachable ClickHouse raises here — failing loudly at
    # startup beats a demo that silently serves a frozen seed.
    clickhouse_sink = ClickHouseSink.from_serving_config()
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
        serving_sink="clickhouse" if clickhouse_sink is not None else "duckdb",
    )

    total = 0
    valid = 0
    invalid = 0
    start_time = time.monotonic()

    try:
        count = burst if burst > 0 else float("inf")
        while total < count:
            _, event = _generate_random_event()
            success, reason = _process_event(
                conn, event, iceberg_sink=iceberg_sink, clickhouse_sink=clickhouse_sink
            )

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
                    rate=_format_rate(total, elapsed),
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
            avg_rate=_format_rate(total, elapsed),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentFlow local pipeline")
    parser.add_argument("--eps", type=int, default=10, help="Events per second")
    parser.add_argument("--burst", type=int, default=0, help="One-shot: N events then stop")
    args = parser.parse_args()
    run(events_per_second=args.eps, burst=args.burst)
