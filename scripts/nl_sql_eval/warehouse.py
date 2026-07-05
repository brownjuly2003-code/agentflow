"""Deterministic in-memory demo warehouse for the NL->SQL eval.

Reuses the production DDL (`src.processing.local_pipeline._ensure_tables`) so
the eval schema can never drift from what the demo actually ships, then seeds a
small fixed dataset.

Timestamps are seeded with DuckDB's own ``NOW() - INTERVAL 'N minutes'`` (never
a Python datetime) so they live in the same timezone domain as the queries'
``NOW()``. Every fact row is recent (< 1 hour old), which makes the rule-based
translator's ``NOW() - INTERVAL '1 hour'`` window a no-op: the harness measures
translation coverage/correctness, not clock-timing precision. That is a
deliberate, documented simplification — see docs/perf/nl-sql-eval-*.md.
"""

from __future__ import annotations

import duckdb

from src.processing.local_pipeline import _ensure_tables

# (order_id, user_id, status, total_amount ₽)
_ORDERS = [
    ("ORD-1001", "USR-1", "delivered", 2490.00),
    ("ORD-1002", "USR-1", "delivered", 1690.00),
    ("ORD-1003", "USR-2", "pending", 4200.00),
    ("ORD-1004", "USR-2", "cancelled", 990.00),
    ("ORD-1005", "USR-3", "delivered", 6990.00),
    ("ORD-1006", "USR-3", "cancelled", 1590.00),
    ("ORD-1007", "USR-1", "delivered", 890.00),
    ("ORD-1008", "USR-4", "pending", 3490.00),
]

# (product_id, name, category, price ₽, in_stock, stock_quantity) — kitchen-appliance
# legend, generator-spec.md §3 categories/RRC bands
_PRODUCTS = [
    ("PRD-1", "Electric Kettle 1.7L 2200W", "kettles", 2190.00, True, 120),
    ("PRD-2", "Stand Mixer 5L Planetary", "mixers", 6990.00, True, 45),
    ("PRD-3", "Cold-Press Juicer", "juicers", 4490.00, False, 0),
    ("PRD-4", "Air Fryer Grill 5.5L", "grills", 5490.00, True, 8),
    ("PRD-5", "Digital Kitchen Scale 5kg", "scales", 990.00, True, 60),
    ("PRD-6", "Mini Chopper 500ml", "choppers", 1490.00, False, 0),
]

# (session_id, user_id, is_conversion)
_SESSIONS = [
    ("SES-1", "USR-1", True),
    ("SES-2", "USR-2", False),
    ("SES-3", "USR-3", True),
    ("SES-4", "USR-4", False),
    ("SES-5", "USR-1", False),
]


def build_demo_warehouse() -> duckdb.DuckDBPyConnection:
    """Return a fresh in-memory DuckDB seeded with the fixed demo dataset."""
    conn = duckdb.connect(":memory:")
    _ensure_tables(conn)

    for order_id, user_id, status, amount in _ORDERS:
        conn.execute(
            "INSERT INTO orders_v2 "
            "(order_id, user_id, status, total_amount, currency, created_at) "
            "VALUES (?, ?, ?, ?, 'RUB', NOW() - INTERVAL '5 minutes')",
            [order_id, user_id, status, amount],
        )

    for product_id, name, category, price, in_stock, qty in _PRODUCTS:
        conn.execute(
            "INSERT INTO products_current "
            "(product_id, name, category, price, in_stock, stock_quantity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [product_id, name, category, price, in_stock, qty],
        )

    for session_id, user_id, is_conversion in _SESSIONS:
        conn.execute(
            "INSERT INTO sessions_aggregated "
            "(session_id, user_id, started_at, ended_at, duration_seconds, "
            " event_count, unique_pages, funnel_stage, is_conversion) "
            "VALUES (?, ?, NOW() - INTERVAL '5 minutes', NULL, 0, 1, 1, "
            "        CASE WHEN ? THEN 'checkout' ELSE 'home' END, ?)",
            [session_id, user_id, is_conversion, is_conversion],
        )

    # Derive user aggregates exactly as the production upsert does
    # (COUNT/SUM over non-cancelled orders), so users_enriched stays consistent
    # with orders_v2 without hand-maintaining a second copy of the numbers.
    conn.execute(
        """
        INSERT INTO users_enriched
        (user_id, total_orders, total_spent, first_order_at, last_order_at, preferred_category)
        SELECT user_id, COUNT(*), SUM(total_amount), MIN(created_at), MAX(created_at), NULL
        FROM orders_v2
        WHERE status != 'cancelled'
        GROUP BY user_id
        """
    )
    return conn
