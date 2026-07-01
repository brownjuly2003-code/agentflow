"""Labelled gold set for the NL->SQL eval over the demo warehouse.

Each item is a natural-language question plus the gold SQL that answers it
against the schema seeded by `warehouse.build_demo_warehouse`. `category`
splits the set into questions the shipped rule-based translator is designed to
handle ("in-pattern") and questions outside its seven regexes ("out-of-pattern"),
so the report can show coverage honestly rather than as a single blended number.

Gold SQL is plain DuckDB. Column *names* are never compared (see metrics), so
gold uses whatever projection is natural for the question.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GoldItem:
    id: str
    question: str
    gold_sql: str
    category: str  # "in-pattern" | "out-of-pattern"


GOLD_SET: list[GoldItem] = [
    # --- in-pattern: the seven rule-based shapes ------------------------------
    GoldItem(
        id="revenue_total",
        question="What is the total revenue?",
        gold_sql="SELECT SUM(total_amount) FROM orders_v2 WHERE status != 'cancelled'",
        category="in-pattern",
    ),
    GoldItem(
        id="revenue_window",
        question="How much revenue did we make in the last hour?",
        gold_sql="SELECT SUM(total_amount) FROM orders_v2 WHERE status != 'cancelled'",
        category="in-pattern",
    ),
    GoldItem(
        id="avg_order_value",
        question="What is the average order value?",
        gold_sql="SELECT AVG(total_amount) FROM orders_v2 WHERE status != 'cancelled'",
        category="in-pattern",
    ),
    GoldItem(
        id="top_products",
        question="Show me the top 3 products by price.",
        gold_sql=(
            "SELECT name, category, price, stock_quantity FROM products_current "
            "ORDER BY price DESC LIMIT 3"
        ),
        category="in-pattern",
    ),
    GoldItem(
        id="conversion_rate",
        question="What is the conversion rate?",
        gold_sql=(
            "SELECT CAST(SUM(CASE WHEN is_conversion THEN 1 ELSE 0 END) AS FLOAT) "
            "/ NULLIF(COUNT(*), 0) FROM sessions_aggregated"
        ),
        category="in-pattern",
    ),
    GoldItem(
        id="out_of_stock",
        question="Which products are out of stock?",
        gold_sql=(
            "SELECT product_id, name, category, stock_quantity FROM products_current "
            "WHERE in_stock = FALSE OR stock_quantity = 0"
        ),
        category="in-pattern",
    ),
    GoldItem(
        id="order_lookup",
        question="Show me order ORD-1003.",
        gold_sql="SELECT * FROM orders_v2 WHERE order_id = 'ORD-1003'",
        category="in-pattern",
    ),
    GoldItem(
        id="active_sessions",
        question="How many active sessions are there right now?",
        gold_sql=(
            "SELECT COUNT(*) FROM sessions_aggregated "
            "WHERE started_at >= NOW() - INTERVAL '30 minutes' AND ended_at IS NULL"
        ),
        category="in-pattern",
    ),
    # --- out-of-pattern: rule-based returns None (untranslatable) --------------
    GoldItem(
        id="cancelled_count",
        question="How many orders were cancelled?",
        gold_sql="SELECT COUNT(*) FROM orders_v2 WHERE status = 'cancelled'",
        category="out-of-pattern",
    ),
    GoldItem(
        id="orders_by_status",
        question="How many orders are there for each status?",
        gold_sql="SELECT status, COUNT(*) FROM orders_v2 GROUP BY status",
        category="out-of-pattern",
    ),
    GoldItem(
        id="most_expensive_product",
        question="What is the most expensive product?",
        gold_sql="SELECT name FROM products_current ORDER BY price DESC LIMIT 1",
        category="out-of-pattern",
    ),
    GoldItem(
        id="products_in_category",
        question="How many products are in the Electronics category?",
        gold_sql="SELECT COUNT(*) FROM products_current WHERE category = 'Electronics'",
        category="out-of-pattern",
    ),
    GoldItem(
        id="total_order_count",
        question="What is the total number of orders?",
        gold_sql="SELECT COUNT(*) FROM orders_v2",
        category="out-of-pattern",
    ),
    GoldItem(
        id="top_spender",
        question="Which user has spent the most money?",
        gold_sql="SELECT user_id FROM users_enriched ORDER BY total_spent DESC LIMIT 1",
        category="out-of-pattern",
    ),
    GoldItem(
        id="avg_product_price",
        question="What is the average product price?",
        gold_sql="SELECT AVG(price) FROM products_current",
        category="out-of-pattern",
    ),
    GoldItem(
        id="converted_sessions",
        question="How many sessions converted?",
        gold_sql="SELECT COUNT(*) FROM sessions_aggregated WHERE is_conversion",
        category="out-of-pattern",
    ),
    GoldItem(
        id="distinct_categories",
        question="List all product categories.",
        gold_sql="SELECT DISTINCT category FROM products_current",
        category="out-of-pattern",
    ),
    GoldItem(
        id="user_count",
        question="How many users do we have?",
        gold_sql="SELECT COUNT(*) FROM users_enriched",
        category="out-of-pattern",
    ),
]
