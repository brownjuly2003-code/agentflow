from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import duckdb

from src.serving.backends import BackendExecutionError, BackendMissingTableError, ServingBackend
from src.serving.db_pool import DuckDBPool


class DuckDBBackend(ServingBackend):
    name = "duckdb"

    def __init__(
        self,
        db_path: str,
        db_pool: DuckDBPool | None = None,
        connection: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        self.db_path = db_path
        self._db_pool = db_pool
        self._conn = (
            connection
            if connection is not None
            else (
                self._db_pool.write_connection
                if self._db_pool is not None
                else duckdb.connect(self.db_path)
            )
        )

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._conn

    @contextmanager
    def read_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        if self._db_pool is None:
            yield self._conn
            return
        with self._db_pool.read_conn() as conn:
            yield conn

    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        try:
            with self.read_connection() as conn:
                rows = conn.execute(sql, params or []).fetchall()
                columns = [desc[0] for desc in conn.description]
        except duckdb.CatalogException as exc:
            raise BackendMissingTableError(str(exc)) from exc
        except duckdb.Error as exc:
            raise BackendExecutionError(str(exc)) from exc
        return [dict(zip(columns, row, strict=False)) for row in rows]

    def scalar(self, sql: str, params: list | None = None):
        try:
            with self.read_connection() as conn:
                row = conn.execute(sql, params or []).fetchone()
        except duckdb.CatalogException as exc:
            raise BackendMissingTableError(str(exc)) from exc
        except duckdb.Error as exc:
            raise BackendExecutionError(str(exc)) from exc
        if row is None:
            return None
        return row[0]

    def table_columns(self, table_name: str) -> set[str]:
        try:
            with self.read_connection() as conn:
                conn.execute(f"SELECT * FROM {table_name} LIMIT 0")  # nosec B608 - table names come from internal catalog/config lookups
                return {desc[0] for desc in conn.description}
        except duckdb.CatalogException:
            return set()
        except duckdb.Error as exc:
            raise BackendExecutionError(str(exc)) from exc

    def explain(self, sql: str) -> list[tuple]:
        try:
            with self.read_connection() as conn:
                return conn.execute(f"EXPLAIN {sql}").fetchall()
        except duckdb.CatalogException as exc:
            raise BackendMissingTableError(str(exc)) from exc
        except duckdb.Error as exc:
            raise BackendExecutionError(str(exc)) from exc

    def initialize_demo_data(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS orders_v2 (
                order_id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                status VARCHAR,
                total_amount DECIMAL(10,2),
                currency VARCHAR DEFAULT 'USD',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS products_current (
                product_id VARCHAR PRIMARY KEY,
                name VARCHAR,
                category VARCHAR,
                price DECIMAL(10,2),
                in_stock BOOLEAN DEFAULT TRUE,
                stock_quantity INTEGER DEFAULT 0
            )
        """)
        self._conn.execute("""
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
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS users_enriched (
                user_id VARCHAR PRIMARY KEY,
                total_orders INTEGER DEFAULT 0,
                total_spent DECIMAL(10,2) DEFAULT 0,
                first_order_at TIMESTAMP,
                last_order_at TIMESTAMP,
                preferred_category VARCHAR
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_events (
                event_id VARCHAR,
                topic VARCHAR,
                tenant_id VARCHAR DEFAULT 'default',
                entity_id VARCHAR,
                event_type VARCHAR,
                latency_ms INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute(
            "ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS tenant_id VARCHAR DEFAULT 'default'"
        )
        self._conn.execute(
            "ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS entity_id VARCHAR"
        )
        self._conn.execute(
            "ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS event_type VARCHAR"
        )
        self._conn.execute(
            "ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS latency_ms INTEGER"
        )

        row = self._conn.execute("SELECT COUNT(*) FROM orders_v2").fetchone()
        count = row[0] if row else 0
        if count > 0:
            return

        self._conn.execute("""
            INSERT INTO products_current VALUES
            ('PROD-001', 'Wireless Headphones', 'electronics', 79.99, TRUE, 142),
            ('PROD-002', 'Running Shoes', 'footwear', 129.99, TRUE, 58),
            ('PROD-003', 'Coffee Maker', 'kitchen', 49.99, TRUE, 203),
            ('PROD-004', 'Mechanical Keyboard', 'electronics', 149.99, TRUE, 37),
            ('PROD-005', 'Yoga Mat', 'fitness', 34.99, TRUE, 315),
            ('PROD-006', 'Backpack', 'accessories', 89.99, TRUE, 94),
            ('PROD-007', 'Water Bottle', 'fitness', 24.99, TRUE, 421),
            ('PROD-008', 'Desk Lamp', 'home', 44.99, FALSE, 0),
            ('PROD-009', 'Bluetooth Speaker', 'electronics', 59.99, TRUE, 167),
            ('PROD-010', 'Sunglasses', 'accessories', 119.99, TRUE, 72)
        """)

        self._conn.execute("""
            INSERT INTO orders_v2 VALUES
            ('ORD-20260404-1001', 'USR-10001', 'delivered',
             159.98, 'USD', NOW() - INTERVAL '2 hours'),
            ('ORD-20260404-1002', 'USR-10002', 'shipped',
             129.99, 'USD', NOW() - INTERVAL '90 minutes'),
            ('ORD-20260404-1003', 'USR-10001', 'confirmed',
             249.97, 'USD', NOW() - INTERVAL '1 hour'),
            ('ORD-20260404-1004', 'USR-10003', 'pending',
             79.99, 'USD', NOW() - INTERVAL '45 minutes'),
            ('ORD-20260404-1005', 'USR-10004', 'delivered',
             89.99, 'USD', NOW() - INTERVAL '30 minutes'),
            ('ORD-20260404-1006', 'USR-10002', 'cancelled',
             34.99, 'USD', NOW() - INTERVAL '20 minutes'),
            ('ORD-20260404-1007', 'USR-10005', 'confirmed',
             179.98, 'USD', NOW() - INTERVAL '15 minutes'),
            ('ORD-20260404-1008', 'USR-10003', 'pending',
             59.99, 'USD', NOW() - INTERVAL '5 minutes')
        """)

        self._conn.execute("""
            INSERT INTO users_enriched VALUES
            ('USR-10001', 15, 2340.50, NOW() - INTERVAL '180 days',
             NOW() - INTERVAL '1 hour', 'electronics'),
            ('USR-10002', 8, 890.20, NOW() - INTERVAL '90 days',
             NOW() - INTERVAL '20 minutes', 'footwear'),
            ('USR-10003', 3, 210.00, NOW() - INTERVAL '30 days',
             NOW() - INTERVAL '5 minutes', 'electronics'),
            ('USR-10004', 22, 4100.75, NOW() - INTERVAL '365 days',
             NOW() - INTERVAL '30 minutes', 'accessories'),
            ('USR-10005', 1, 179.98, NOW() - INTERVAL '1 day',
             NOW() - INTERVAL '15 minutes', 'electronics')
        """)

        self._conn.execute("""
            INSERT INTO sessions_aggregated VALUES
            ('SES-a1b2c3', 'USR-10001',
             NOW() - INTERVAL '2 hours',
             NOW() - INTERVAL '100 minutes',
             1200, 14, 6, 'checkout', TRUE),
            ('SES-d4e5f6', 'USR-10002',
             NOW() - INTERVAL '90 minutes',
             NOW() - INTERVAL '70 minutes',
             1200, 8, 4, 'add_to_cart', FALSE),
            ('SES-g7h8i9', NULL,
             NOW() - INTERVAL '60 minutes',
             NOW() - INTERVAL '58 minutes',
             120, 2, 2, 'bounce', FALSE),
            ('SES-j1k2l3', 'USR-10003',
             NOW() - INTERVAL '45 minutes',
             NOW() - INTERVAL '20 minutes',
             1500, 11, 5, 'checkout', TRUE),
            ('SES-m4n5o6', 'USR-10004',
             NOW() - INTERVAL '30 minutes',
             NOW() - INTERVAL '15 minutes',
             900, 6, 3, 'product_view', FALSE),
            ('SES-p7q8r9', 'USR-10005',
             NOW() - INTERVAL '20 minutes',
             NULL, NULL, 3, 2, 'browse', FALSE)
        """)

        # Seed pipeline_events with entity_id rows so /v1/lineage and SDK
        # contract tests have deterministic lineage data for the canonical
        # ORD-20260404-1001 order. Older 10 events kept as ambient noise.
        self._conn.execute("""
            INSERT INTO pipeline_events
                (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at)
            VALUES
            ('evt-001', 'events.validated', 'default', NULL, NULL, NULL, NOW() - INTERVAL '10 minutes'),
            ('evt-002', 'events.validated', 'default', NULL, NULL, NULL, NOW() - INTERVAL '9 minutes'),
            ('evt-003', 'events.validated', 'default', NULL, NULL, NULL, NOW() - INTERVAL '8 minutes'),
            ('evt-004', 'events.deadletter', 'default', NULL, NULL, NULL, NOW() - INTERVAL '7 minutes'),
            ('evt-005', 'events.validated', 'default', NULL, NULL, NULL, NOW() - INTERVAL '6 minutes'),
            ('evt-006', 'events.validated', 'default', NULL, NULL, NULL, NOW() - INTERVAL '5 minutes'),
            ('evt-007', 'events.validated', 'default', NULL, NULL, NULL, NOW() - INTERVAL '4 minutes'),
            ('evt-008', 'events.validated', 'default', NULL, NULL, NULL, NOW() - INTERVAL '3 minutes'),
            ('evt-009', 'events.deadletter', 'default', NULL, NULL, NULL, NOW() - INTERVAL '2 minutes'),
            ('evt-010', 'events.validated', 'default', NULL, NULL, NULL, NOW() - INTERVAL '1 minute'),
            -- Lineage trail for ORD-20260404-1001 (ingestion -> validation -> serving)
            ('evt-ord-1001-ingest', 'orders.raw', 'default', 'ORD-20260404-1001',
                'order.created', 12, NOW() - INTERVAL '3 minutes'),
            ('evt-ord-1001-validated', 'events.validated', 'default', 'ORD-20260404-1001',
                'order.validated', 8, NOW() - INTERVAL '2 minutes'),
            ('evt-ord-1001-served', 'events.served', 'default', 'ORD-20260404-1001',
                'order.served', 4, NOW() - INTERVAL '1 minute')
        """)

    def health(self) -> dict:
        try:
            value = self.scalar("SELECT 1")
        except BackendExecutionError as exc:
            return {"backend": self.name, "status": "error", "error": str(exc)}
        return {
            "backend": self.name,
            "status": "ok" if value == 1 else "error",
            "db_path": self.db_path,
        }
