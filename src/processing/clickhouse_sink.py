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

    def existing_event_ids(self, event_ids: list[str]) -> set[str]:
        """Which of ``event_ids`` the serving journal has already seen.

        The idempotency guard for the S6 bridge. Scoped exactly like the
        node-ingest guard (``src/serving/node/ingest.py``): ``event_id`` is
        unique only *within* the two ingest topics, because derived rows such
        as the ``orders.status`` journal entry deliberately reuse the same
        ``event_id`` with a suffix.

        Unlike node-ingest, this filters by the batch's ids in SQL rather than
        scanning the whole journal and intersecting in Python: the bridge is a
        sustained writer, so an O(table) read per batch would grow without
        bound. ``event_id`` is not the leading key of the ClickHouse sort order
        (``clickhouse_backend.ensure_schema``), so this is not a point lookup —
        but it is bounded by the batch, not by the table.

        This asks the *serving* store, not the bridge's scratch lake: on the
        ClickHouse path the serving-store mirror happens after the local
        commit, so a crash in between must leave the event replayable.
        """
        if not event_ids:
            return set()
        quoted = ", ".join(_quote_literal(str(event_id)) for event_id in event_ids)
        rows = self._backend.execute(
            "SELECT DISTINCT event_id FROM pipeline_events "  # nosec B608 - quoted literals, re-escaped structurally by the backend transpile
            f"WHERE event_id IN ({quoted}) "
            "AND topic IN ('events.validated', 'events.deadletter')"
        )
        return {str(row["event_id"]) for row in rows}

    def record_pipeline_event(
        self,
        *,
        event_id: str,
        topic: str,
        tenant_id: str,
        event_type: str,
        latency_ms: int | None,
        entity_id: str | None = None,
        processed_at: datetime | None = None,
    ) -> None:
        self.record_pipeline_events(
            [
                {
                    "event_id": event_id,
                    "topic": topic,
                    "tenant_id": tenant_id,
                    "entity_id": entity_id,
                    "event_type": event_type,
                    "latency_ms": latency_ms,
                    "processed_at": processed_at or datetime.now(UTC),
                }
            ]
        )

    def record_pipeline_events(self, rows: list[dict[str, Any]]) -> None:
        """Multi-row journal write (Q1.3). One HTTP insert for the whole list."""
        if not rows:
            return
        normalized: list[dict[str, Any]] = []
        for row in rows:
            normalized.append(
                {
                    "event_id": row["event_id"],
                    "topic": row["topic"],
                    "tenant_id": row["tenant_id"],
                    "entity_id": row.get("entity_id"),
                    "event_type": row["event_type"],
                    "latency_ms": row.get("latency_ms"),
                    "processed_at": row.get("processed_at") or datetime.now(UTC),
                }
            )
        self._backend.insert_rows("pipeline_events", normalized)

    def upsert_order(self, event: dict, *, refresh_user: bool = True) -> None:
        """Append one order version. Optionally refresh ``users_enriched``.

        ``refresh_user=False`` is for the bridge batch path (Q1.3): many orders
        share a user; the bridge calls :meth:`refresh_user_aggregates` once per
        unique user after the multi-row order insert.
        """
        self.insert_orders([event])
        if refresh_user:
            self._refresh_user_aggregate(str(event["user_id"]))

    def insert_orders(self, events: list[dict]) -> None:
        """Multi-row ``orders_v2`` insert (ReplacingMergeTree append versions)."""
        if not events:
            return
        rows = [
            {
                "order_id": event["order_id"],
                "user_id": event["user_id"],
                "status": event["status"],
                "total_amount": float(event["total_amount"]),
                "currency": event.get("currency", "RUB"),
                "created_at": datetime.fromisoformat(event["timestamp"]),
            }
            for event in events
        ]
        self._backend.insert_rows("orders_v2", rows)

    def insert_products(self, events: list[dict]) -> None:
        if not events:
            return
        rows = [
            {
                "product_id": event["product_id"],
                "name": event["name"],
                "category": event["category"],
                "price": float(event["price"]),
                "in_stock": bool(event["in_stock"]),
                "stock_quantity": int(event["stock_quantity"]),
            }
            for event in events
        ]
        self._backend.insert_rows("products_current", rows)

    def refresh_user_aggregates(self, user_ids: set[str] | list[str]) -> None:
        """Recompute ``users_enriched`` once per user (amortized batch end)."""
        for user_id in sorted({str(uid) for uid in user_ids if uid}):
            self._refresh_user_aggregate(user_id)

    def _refresh_user_aggregate(self, user_id: str) -> None:
        # Same aggregate the dual-write path materializes in _upsert_order;
        # written as an append of a new users_enriched row version on ClickHouse.
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
        self.insert_products([event])

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
