from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp

from src.serving.backends import BackendExecutionError, BackendMissingTableError, ServingBackend
from src.serving.control_plane import ensure_dead_letter_table
from src.serving.db_pool import DuckDBPool
from src.serving.duckdb_connection import connect_duckdb

# Strict identifier validation for f-string SQL paths (H-C1 / audit-2026-05).
# Accepts either a bare DuckDB identifier (`name` or `schema.name`) or a
# double-quoted identifier (`"name"` / `"schema"."name"`), the form produced
# by `SQLBuilderMixin._quote_identifier` for tenant-scoped tables. Inside
# double quotes any character is legal except a lone `"` — `""` is the
# DuckDB-escaped form of an embedded quote. Bare-identifier injection
# payloads (`"; DROP TABLE`, `WHERE 1=1`, `--`) all fail to match either
# alternative.
_IDENTIFIER_PART = r'(?:[A-Za-z_][A-Za-z0-9_]*|"(?:[^"]|"")+")'
_IDENTIFIER_RE = re.compile(rf"^{_IDENTIFIER_PART}(?:\.{_IDENTIFIER_PART})?$")


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
                else connect_duckdb(self.db_path)
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

    def scalar(self, sql: str, params: list | None = None) -> Any:
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
        # H-C1: reject anything that is not a bare identifier or `schema.identifier`.
        # The f-string SQL path means a malformed name would otherwise be
        # interpolated raw into the query — caller should already pass a
        # catalog-resolved name, but enforce the invariant in code.
        if not _IDENTIFIER_RE.match(table_name):
            return set()
        try:
            with self.read_connection() as conn:
                # identifier validated above
                conn.execute(f"SELECT * FROM {table_name} LIMIT 0")  # nosec B608
                return {desc[0] for desc in conn.description}
        except duckdb.CatalogException:
            return set()
        except duckdb.Error as exc:
            raise BackendExecutionError(str(exc)) from exc

    def explain(self, sql: str) -> list[tuple]:
        # H-C1: require the input to parse as a single SELECT statement
        # before splicing it into `EXPLAIN <sql>`. The semantic layer's
        # NL-to-SQL pipeline already validates via `sql_guard.validate_nl_sql`,
        # but `explain()` is also reachable from other call sites and must
        # not be a back-door for `EXPLAIN ; DROP TABLE ...` style injection.
        try:
            statements = sqlglot.parse(sql, dialect="duckdb")
        except sqlglot.errors.ParseError as exc:
            raise BackendExecutionError(f"Unparseable SQL: {exc}") from exc
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            raise BackendExecutionError("EXPLAIN only supports a single SELECT statement")
        try:
            with self.read_connection() as conn:
                # statement validated above
                return conn.execute(f"EXPLAIN {sql}").fetchall()  # nosec B608
        except duckdb.CatalogException as exc:
            raise BackendMissingTableError(str(exc)) from exc
        except duckdb.Error as exc:
            raise BackendExecutionError(str(exc)) from exc

    def ensure_schema(self) -> None:
        # The embedded store is this process's own: :memory: by default, with no
        # other provisioner and nothing to migrate from. Creating its tables is
        # not the external-store DDL that audit P0-2 forbids the API to issue.
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS orders_v2 (
                order_id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                status VARCHAR,
                total_amount DECIMAL(10,2),
                currency VARCHAR DEFAULT 'RUB',
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
        self._conn.execute("ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS entity_id VARCHAR")
        self._conn.execute(
            "ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS event_type VARCHAR"
        )
        self._conn.execute(
            "ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS latency_ms INTEGER"
        )
        # ADR 0012 N4: federated node events carry their originating branch on
        # the journal; NULL for the standalone demo's in-process events.
        self._conn.execute("ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS branch VARCHAR")

    def seed_demo_data(self) -> None:
        row = self._conn.execute("SELECT COUNT(*) FROM orders_v2").fetchone()
        count = row[0] if row else 0
        if count > 0:
            return

        self._conn.execute("""
            INSERT INTO products_current VALUES
            ('PROD-001', 'Electric Kettle 1.7L 2200W', 'kettles', 2190.00, FALSE, 0),
            ('PROD-002', 'Air Fryer Grill 5.5L', 'grills', 5490.00, TRUE, 58),
            ('PROD-003', 'Immersion Blender Set 800W', 'blenders', 2490.00, TRUE, 203),
            ('PROD-004', 'Stand Mixer 5L Planetary', 'mixers', 6990.00, TRUE, 37),
            ('PROD-005', 'Drip Coffee Maker 1.2L', 'coffee', 3490.00, TRUE, 94),
            ('PROD-006', 'Waffle Maker Double', 'multibakers', 2290.00, TRUE, 142),
            ('PROD-007', 'Mini Chopper 500ml', 'choppers', 1490.00, TRUE, 315),
            ('PROD-008', 'Cold-Press Juicer', 'juicers', 4490.00, TRUE, 72),
            ('PROD-009', 'Digital Kitchen Scale 5kg', 'scales', 990.00, TRUE, 421),
            ('PROD-010', 'Vacuum Sealer Compact', 'vacuum-dry', 3290.00, TRUE, 167)
        """)

        self._conn.execute("""
            INSERT INTO orders_v2 VALUES
            ('ORD-20260404-1001', 'USR-10001', 'delivered',
             76400.00, 'RUB', NOW() - INTERVAL '2 hours'),
            ('ORD-20260404-1002', 'USR-10002', 'shipped',
             48100.00, 'RUB', NOW() - INTERVAL '90 minutes'),
            ('ORD-20260404-1003', 'USR-10003', 'confirmed',
             2650.00, 'RUB', NOW() - INTERVAL '1 hour'),
            ('ORD-20260404-1004', 'USR-10003', 'pending',
             1890.00, 'RUB', NOW() - INTERVAL '45 minutes'),
            ('ORD-20260404-1005', 'USR-10004', 'delivered',
             2290.00, 'RUB', NOW() - INTERVAL '30 minutes'),
            ('ORD-20260404-1006', 'USR-10004', 'cancelled',
             1590.00, 'RUB', NOW() - INTERVAL '20 minutes'),
            ('ORD-20260404-1007', 'USR-10005', 'confirmed',
             2990.00, 'RUB', NOW() - INTERVAL '15 minutes'),
            ('ORD-20260404-1008', 'USR-10005', 'pending',
             3990.00, 'RUB', NOW() - INTERVAL '5 minutes')
        """)

        self._conn.execute("""
            INSERT INTO users_enriched VALUES
            ('USR-10001', 34, 1200000.00, NOW() - INTERVAL '365 days',
             NOW() - INTERVAL '2 hours', 'grills'),
            ('USR-10002', 15, 460000.00, NOW() - INTERVAL '270 days',
             NOW() - INTERVAL '90 minutes', 'coffee'),
            ('USR-10003', 4, 8900.00, NOW() - INTERVAL '60 days',
             NOW() - INTERVAL '45 minutes', 'choppers'),
            ('USR-10004', 6, 15800.00, NOW() - INTERVAL '120 days',
             NOW() - INTERVAL '20 minutes', 'blenders'),
            ('USR-10005', 3, 28500.00, NOW() - INTERVAL '10 days',
             NOW() - INTERVAL '5 minutes', 'vacuum-dry')
        """)

        self._conn.execute("""
            INSERT INTO sessions_aggregated VALUES
            ('SES-a1b2c3', 'USR-10005',
             NOW() - INTERVAL '2 hours',
             NOW() - INTERVAL '100 minutes',
             1200, 14, 6, 'checkout', TRUE),
            ('SES-d4e5f6', 'USR-10004',
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

        # Dead-letter store counterparts for the two seeded journal rows above
        # (ops-surfaces-spec.md §4.6, D4): the exception inbox's native
        # source aggregates `dead_letter_events` (control-plane state, always
        # on this connection regardless of SERVING_BACKEND — see
        # QueryEngine.__init__), not `pipeline_events` — without these rows
        # the demo inbox would be empty even though the journal already
        # carries two 'events.deadletter' entries (I7).
        ensure_dead_letter_table(self._conn)
        self._conn.execute("""
            INSERT INTO dead_letter_events
                (event_id, tenant_id, event_type, payload, failure_reason,
                 failure_detail, received_at, retry_count, last_retried_at, status)
            VALUES
            ('evt-004', 'default', 'order.created',
                '{"order_id": "ORD-DRAFT-004", "total_amount": 0}', 'schema_validation',
                'total_amount is below the minimum order threshold',
                NOW() - INTERVAL '7 minutes', 0, NULL, 'failed'),
            ('evt-009', 'default', 'order.updated',
                '{"order_id": "ORD-20260404-1002", "status": "shipped"}', 'duplicate_event',
                'event_id already processed at an earlier journal offset',
                NOW() - INTERVAL '2 minutes', 0, NULL, 'failed')
        """)

        # Stage-entry trails (ops-surfaces-spec.md §1.6): topic='orders.status',
        # one row per stage transition, back-dated between each order's
        # created_at and now. ORD-20260404-1004's single pending entry at
        # created_at is the demo's sole SLA breach (45min vs a 30min budget,
        # once D3 wires the stages: contract block). ORD-20260404-1001 carries
        # the full ladder for the Order 360 story (I7).
        self._conn.execute("""
            INSERT INTO pipeline_events
                (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at)
            VALUES
            ('evt-ord-1001-status-pending', 'orders.status', 'default', 'ORD-20260404-1001',
                'order.status.pending', NULL, NOW() - INTERVAL '120 minutes'),
            ('evt-ord-1001-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1001',
                'order.status.confirmed', NULL, NOW() - INTERVAL '100 minutes'),
            ('evt-ord-1001-status-shipped', 'orders.status', 'default', 'ORD-20260404-1001',
                'order.status.shipped', NULL, NOW() - INTERVAL '60 minutes'),
            ('evt-ord-1001-status-delivered', 'orders.status', 'default', 'ORD-20260404-1001',
                'order.status.delivered', NULL, NOW() - INTERVAL '10 minutes'),
            ('evt-ord-1002-status-pending', 'orders.status', 'default', 'ORD-20260404-1002',
                'order.status.pending', NULL, NOW() - INTERVAL '90 minutes'),
            ('evt-ord-1002-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1002',
                'order.status.confirmed', NULL, NOW() - INTERVAL '80 minutes'),
            ('evt-ord-1002-status-shipped', 'orders.status', 'default', 'ORD-20260404-1002',
                'order.status.shipped', NULL, NOW() - INTERVAL '70 minutes'),
            ('evt-ord-1003-status-pending', 'orders.status', 'default', 'ORD-20260404-1003',
                'order.status.pending', NULL, NOW() - INTERVAL '60 minutes'),
            ('evt-ord-1003-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1003',
                'order.status.confirmed', NULL, NOW() - INTERVAL '50 minutes'),
            ('evt-ord-1004-status-pending', 'orders.status', 'default', 'ORD-20260404-1004',
                'order.status.pending', NULL, NOW() - INTERVAL '45 minutes'),
            ('evt-ord-1005-status-pending', 'orders.status', 'default', 'ORD-20260404-1005',
                'order.status.pending', NULL, NOW() - INTERVAL '30 minutes'),
            ('evt-ord-1005-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1005',
                'order.status.confirmed', NULL, NOW() - INTERVAL '25 minutes'),
            ('evt-ord-1005-status-shipped', 'orders.status', 'default', 'ORD-20260404-1005',
                'order.status.shipped', NULL, NOW() - INTERVAL '15 minutes'),
            ('evt-ord-1005-status-delivered', 'orders.status', 'default', 'ORD-20260404-1005',
                'order.status.delivered', NULL, NOW() - INTERVAL '5 minutes'),
            ('evt-ord-1006-status-pending', 'orders.status', 'default', 'ORD-20260404-1006',
                'order.status.pending', NULL, NOW() - INTERVAL '20 minutes'),
            ('evt-ord-1006-status-cancelled', 'orders.status', 'default', 'ORD-20260404-1006',
                'order.status.cancelled', NULL, NOW() - INTERVAL '10 minutes'),
            ('evt-ord-1007-status-pending', 'orders.status', 'default', 'ORD-20260404-1007',
                'order.status.pending', NULL, NOW() - INTERVAL '15 minutes'),
            ('evt-ord-1007-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1007',
                'order.status.confirmed', NULL, NOW() - INTERVAL '8 minutes'),
            ('evt-ord-1008-status-pending', 'orders.status', 'default', 'ORD-20260404-1008',
                'order.status.pending', NULL, NOW() - INTERVAL '5 minutes')
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
