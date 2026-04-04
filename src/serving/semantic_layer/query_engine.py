"""Query engine — translates agent requests into data lookups.

Supports:
- Natural language → SQL translation (rule-based + template matching)
- Entity lookups by primary key
- Metric computation over time windows

Uses DuckDB for local execution (production would use Iceberg catalog).
"""

import os
import re
import time

import duckdb
import structlog

from src.serving.semantic_layer.catalog import DataCatalog

logger = structlog.get_logger()

# Window string to SQL interval mapping
WINDOW_MAP = {
    "5m": "5 minutes",
    "15m": "15 minutes",
    "1h": "1 hour",
    "6h": "6 hours",
    "24h": "24 hours",
    "now": "30 minutes",
}


class QueryEngine:
    """Executes queries against the data platform."""

    def __init__(self, catalog: DataCatalog, db_path: str | None = None):
        self.catalog = catalog
        self._db_path: str = db_path or os.getenv("DUCKDB_PATH", ":memory:") or ":memory:"
        self._conn = duckdb.connect(self._db_path)
        self._init_sample_data()

    def _init_sample_data(self):
        """Seed DuckDB with all tables declared in the catalog.

        Every entity and metric in the catalog must have a backing table here.
        This ensures the local demo never returns fake 200s for missing tables.
        """
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
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._seed_demo_data()

    def _seed_demo_data(self):
        """Insert realistic sample data so the local demo returns meaningful results."""
        # Only seed if tables are empty
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

        self._conn.execute("""
            INSERT INTO pipeline_events VALUES
            ('evt-001', 'events.validated', NOW() - INTERVAL '10 minutes'),
            ('evt-002', 'events.validated', NOW() - INTERVAL '9 minutes'),
            ('evt-003', 'events.validated', NOW() - INTERVAL '8 minutes'),
            ('evt-004', 'events.deadletter', NOW() - INTERVAL '7 minutes'),
            ('evt-005', 'events.validated', NOW() - INTERVAL '6 minutes'),
            ('evt-006', 'events.validated', NOW() - INTERVAL '5 minutes'),
            ('evt-007', 'events.validated', NOW() - INTERVAL '4 minutes'),
            ('evt-008', 'events.validated', NOW() - INTERVAL '3 minutes'),
            ('evt-009', 'events.deadletter', NOW() - INTERVAL '2 minutes'),
            ('evt-010', 'events.validated', NOW() - INTERVAL '1 minute')
        """)

    def execute_nl_query(
        self, question: str, context: dict | None = None
    ) -> dict:
        """Translate a natural language question to SQL and execute it.

        Uses pattern matching against known query templates.
        For production, this would integrate with an LLM for translation.
        """
        start = time.monotonic()
        sql = self._nl_to_sql(question)

        if not sql:
            msg = (
                f"Could not translate question: '{question}'. "
                f"Try asking about: {list(self.catalog.entities.keys())} "
                f"or metrics: {list(self.catalog.metrics.keys())}"
            )
            raise ValueError(msg)

        try:
            result = self._conn.execute(sql).fetchall()
            columns = [
                desc[0] for desc in self._conn.description
            ]
            data = [dict(zip(columns, row, strict=False)) for row in result]
        except duckdb.Error as e:
            raise ValueError(f"Query execution failed: {e}") from e

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return {
            "data": data,
            "sql": sql,
            "row_count": len(data),
            "execution_time_ms": elapsed_ms,
            "freshness_seconds": None,
        }

    def _nl_to_sql(self, question: str) -> str | None:
        """Simple pattern-based NL→SQL translation.

        Production systems would use an LLM here. This rule-based approach
        handles common agent queries without external dependencies.
        """
        q = question.lower().strip()

        # Order lookups
        order_match = re.search(r"order\s+(ORD-[\w-]+)", question, re.IGNORECASE)
        if order_match:
            oid = order_match.group(1)
            return f"SELECT * FROM orders_v2 WHERE order_id = '{oid}'"

        # Revenue queries
        if "revenue" in q or "total sales" in q:
            window = self._extract_window(q)
            return (
                f"SELECT SUM(total_amount) as revenue "
                f"FROM orders_v2 "
                f"WHERE status != 'cancelled' "
                f"AND created_at >= NOW() - INTERVAL '{window}'"
            )

        # Average order value
        if "average order" in q or "avg order" in q or "aov" in q:
            window = self._extract_window(q)
            return (
                f"SELECT AVG(total_amount) as avg_order_value "
                f"FROM orders_v2 "
                f"WHERE status != 'cancelled' "
                f"AND created_at >= NOW() - INTERVAL '{window}'"
            )

        # Top products
        if "top" in q and "product" in q:
            limit = 5
            limit_match = re.search(r"top\s+(\d+)", q)
            if limit_match:
                limit = int(limit_match.group(1))
            return (
                f"SELECT name, category, price, stock_quantity "
                f"FROM products_current "
                f"ORDER BY price DESC "
                f"LIMIT {limit}"
            )

        # Conversion rate
        if "conversion" in q:
            window = self._extract_window(q)
            return (
                f"SELECT "
                f"COUNT(*) FILTER (WHERE is_conversion) as conversions, "
                f"COUNT(*) as total_sessions, "
                f"ROUND(COUNT(*) FILTER (WHERE is_conversion)::FLOAT "
                f"/ NULLIF(COUNT(*), 0) * 100, 2) as conversion_pct "
                f"FROM sessions_aggregated "
                f"WHERE started_at >= NOW() - INTERVAL '{window}'"
            )

        return None

    def _extract_window(self, question: str) -> str:
        """Extract time window from natural language."""
        patterns = {
            r"last\s+(\d+)\s*min": lambda m: f"{m.group(1)} minutes",
            r"last\s+(\d+)\s*hour": lambda m: f"{m.group(1)} hours",
            r"last\s+(\d+)\s*day": lambda m: f"{m.group(1)} days",
            r"today": lambda _: "24 hours",
            r"this\s+hour": lambda _: "1 hour",
        }
        for pattern, builder in patterns.items():
            match = re.search(pattern, question)
            if match:
                return builder(match)
        return "1 hour"  # default

    def get_entity(self, entity_type: str, entity_id: str) -> dict | None:
        """Look up a single entity by type and ID.

        Raises ValueError if the backing table doesn't exist or query fails.
        Returns None only when the entity genuinely doesn't exist in the table.
        """
        entity_def = self.catalog.entities.get(entity_type)
        if not entity_def:
            return None

        sql = (
            f"SELECT * FROM {entity_def.table} "
            f"WHERE {entity_def.primary_key} = ?"
        )
        try:
            result = self._conn.execute(sql, [entity_id]).fetchone()
        except duckdb.CatalogException as e:
            msg = (
                f"Table '{entity_def.table}' for entity '{entity_type}' "
                f"is not materialized yet"
            )
            raise ValueError(msg) from e
        except duckdb.Error as e:
            raise ValueError(f"Entity lookup failed: {e}") from e

        if not result:
            return None
        columns = [desc[0] for desc in self._conn.description]
        return dict(zip(columns, result, strict=False))

    def get_metric(self, metric_name: str, window: str = "1h") -> dict:
        """Compute a metric value for the given time window.

        Raises ValueError if the backing table doesn't exist.
        Returns value=0 only when the query succeeds but yields no data.
        """
        metric_def = self.catalog.metrics.get(metric_name)
        if not metric_def:
            return {"value": 0, "unit": "unknown"}

        sql_interval = WINDOW_MAP.get(window, "1 hour")
        sql = metric_def.sql_template.format(window=sql_interval)

        try:
            result = self._conn.execute(sql).fetchone()
            value = float(result[0]) if result and result[0] is not None else 0.0
        except duckdb.CatalogException as e:
            table_match = re.search(r"Table.*?(\w+).*?not found", str(e))
            table_name = table_match.group(1) if table_match else "unknown"
            raise ValueError(
                f"Metric '{metric_name}' depends on table '{table_name}' "
                f"which is not materialized yet"
            ) from e
        except duckdb.Error as e:
            raise ValueError(f"Metric query failed: {e}") from e

        return {
            "value": round(value, 4),
            "unit": metric_def.unit,
        }
