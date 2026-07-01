"""ClickHouse serving sink for the local pipeline.

When the configured serving backend is ClickHouse (ADR 0006), the local
pipeline mirrors its serving-table writes here so the *serving store the API
reads* is the one that moves when events happen. DuckDB stays the local
lake/test store (it keeps the benchmark fixtures and the no-Docker test paths),
mirroring the production topology where Flink writes both the lakehouse and
the serving store.

Upsert model: the mutable serving tables are ReplacingMergeTree keyed by their
id column with a MATERIALIZED ``af_updated_at`` version (see
``ClickHouseBackend.ensure_schema``). An upsert is therefore *append a full new
row version*; reads run with ``final=1`` and see only the latest version. The
single-writer demo pipeline is the only writer, so version ordering is the
insert order.

Reads issued by this sink (the user/session aggregate recomputes) are written
in the same DuckDB-flavored SQL as the semantic layer and go through the same
``_translate_sql`` transpile — one dialect end to end, per ADR 0006.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.serving.backends import load_serving_backend_config
from src.serving.backends.clickhouse_backend import ClickHouseBackend

_FUNNEL_STAGE_ORDER = {
    "checkout": 4,
    "cart": 3,
    "product_detail": 2,
    "search": 1,
    "home": 0,
    "other": 0,
}


def _quote_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class ClickHouseSink:
    """Writes pipeline output to the ClickHouse serving store."""

    def __init__(self, backend: ClickHouseBackend) -> None:
        self._backend = backend
        # Idempotent: creates the schema and seeds the canonical demo rows only
        # when the store is empty, so the documented demo entities
        # (ORD-20260404-1001, ...) exist regardless of bring-up order.
        backend.initialize_demo_data()

    @classmethod
    def from_serving_config(cls, config_path: str | None = None) -> ClickHouseSink | None:
        """Build a sink iff the configured serving backend is ClickHouse.

        Returns ``None`` on the DuckDB path. A configured-but-unreachable
        ClickHouse raises: silently skipping the serving-store write would make
        the demo serve stale data while claiming event-driven freshness.
        """
        config = load_serving_backend_config(config_path)
        if config["backend"] != "clickhouse":
            return None
        clickhouse = config["clickhouse"]
        return cls(
            ClickHouseBackend(
                host=clickhouse["host"],
                port=clickhouse["port"],
                user=clickhouse["user"],
                password=clickhouse["password"],
                database=clickhouse["database"],
                secure=clickhouse["secure"],
                timeout_seconds=clickhouse["timeout_seconds"],
            )
        )

    def record_pipeline_event(
        self,
        *,
        event_id: str,
        topic: str,
        tenant_id: str,
        event_type: str,
        latency_ms: int,
        processed_at: datetime | None = None,
    ) -> None:
        self._backend.insert_rows(
            "pipeline_events",
            [
                {
                    "event_id": event_id,
                    "topic": topic,
                    "tenant_id": tenant_id,
                    "entity_id": None,
                    "event_type": event_type,
                    "latency_ms": latency_ms,
                    "processed_at": processed_at or datetime.now(UTC),
                }
            ],
        )

    def upsert_order(self, event: dict) -> None:
        self._backend.insert_rows(
            "orders_v2",
            [
                {
                    "order_id": event["order_id"],
                    "user_id": event["user_id"],
                    "status": event["status"],
                    "total_amount": float(event["total_amount"]),
                    "currency": event.get("currency", "USD"),
                    "created_at": datetime.fromisoformat(event["timestamp"]),
                }
            ],
        )
        self._refresh_user_aggregate(str(event["user_id"]))

    def _refresh_user_aggregate(self, user_id: str) -> None:
        # Same aggregate the DuckDB path materializes in _upsert_order; written
        # as an append of a new users_enriched row version.
        rows = self._backend.execute(
            "SELECT user_id, COUNT(*) AS total_orders, SUM(total_amount) AS total_spent, "
            "MIN(created_at) AS first_order_at, MAX(created_at) AS last_order_at "
            f"FROM orders_v2 WHERE user_id = {_quote_literal(user_id)} "  # nosec B608 - quoted literal, re-escaped structurally by the backend transpile
            "AND status != 'cancelled' GROUP BY user_id"
        )
        if not rows:
            return
        row = rows[0]
        self._backend.insert_rows(
            "users_enriched",
            [
                {
                    "user_id": str(row["user_id"]),
                    "total_orders": int(row["total_orders"]),
                    "total_spent": float(row["total_spent"]),
                    "first_order_at": row["first_order_at"],
                    "last_order_at": row["last_order_at"],
                    "preferred_category": None,
                }
            ],
        )

    def upsert_product(self, event: dict) -> None:
        self._backend.insert_rows(
            "products_current",
            [
                {
                    "product_id": event["product_id"],
                    "name": event["name"],
                    "category": event["category"],
                    "price": float(event["price"]),
                    "in_stock": bool(event["in_stock"]),
                    "stock_quantity": int(event["stock_quantity"]),
                }
            ],
        )

    def upsert_session(self, event: dict) -> None:
        session_id = str(event.get("session_id", "unknown"))
        derived = event.get("_derived", {})
        page_cat = derived.get("page_category", "other")
        new_stage_val = _FUNNEL_STAGE_ORDER.get(page_cat, 0)

        existing_rows = self._backend.execute(
            "SELECT session_id, user_id, started_at, ended_at, duration_seconds, "
            "event_count, unique_pages, funnel_stage, is_conversion "
            f"FROM sessions_aggregated WHERE session_id = {_quote_literal(session_id)} "  # nosec B608 - quoted literal, re-escaped structurally by the backend transpile
            "LIMIT 1"
        )
        if existing_rows:
            existing: dict[str, Any] = existing_rows[0]
            old_stage = str(existing.get("funnel_stage") or "bounce")
            old_count = int(existing.get("event_count") or 0)
            old_stage_val = _FUNNEL_STAGE_ORDER.get(old_stage, 0)
            funnel = page_cat if new_stage_val > old_stage_val else old_stage
            self._backend.insert_rows(
                "sessions_aggregated",
                [
                    {
                        "session_id": session_id,
                        "user_id": existing.get("user_id"),
                        "started_at": existing.get("started_at"),
                        "ended_at": existing.get("ended_at"),
                        "duration_seconds": existing.get("duration_seconds"),
                        "event_count": old_count + 1,
                        "unique_pages": int(existing.get("unique_pages") or 1),
                        "funnel_stage": funnel,
                        "is_conversion": funnel == "checkout",
                    }
                ],
            )
        else:
            self._backend.insert_rows(
                "sessions_aggregated",
                [
                    {
                        "session_id": session_id,
                        "user_id": event.get("user_id"),
                        "started_at": datetime.now(UTC),
                        "ended_at": None,
                        "duration_seconds": 0,
                        "event_count": 1,
                        "unique_pages": 1,
                        "funnel_stage": page_cat,
                        "is_conversion": page_cat == "checkout",
                    }
                ],
            )
