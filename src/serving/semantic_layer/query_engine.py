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
