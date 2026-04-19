"""LLM-powered NL→SQL engine using Claude API.

Translates natural language agent queries into SQL using the semantic catalog
as schema context. Falls back to rule-based patterns if no API key is set.

Set ANTHROPIC_API_KEY to enable LLM mode.
"""

import os
import re
import time

import structlog

from src.serving.semantic_layer.catalog import DataCatalog

logger = structlog.get_logger()

_ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def _build_schema_prompt(catalog: DataCatalog) -> str:
    """Build a schema description for the LLM from the catalog."""
    lines = ["Available tables and columns:\n"]
    for name, entity in catalog.entities.items():
        fields = ", ".join(
            f"{f} ({desc})" for f, desc in entity.fields.items()
        )
        lines.append(f"- {entity.table} (entity: {name}): {fields}")

    lines.append("\nAvailable metrics:")
    for name, metric in catalog.metrics.items():
        lines.append(f"- {name}: {metric.description} (unit: {metric.unit})")

    return "\n".join(lines)


def translate_nl_to_sql(
    question: str,
    catalog: DataCatalog,
) -> str | None:
    """Translate natural language to SQL.

    Uses Claude API if ANTHROPIC_API_KEY is set, otherwise falls back
    to rule-based patterns.
    """
    if _ANTHROPIC_KEY:
        return _llm_translate(question, catalog)
    return _rule_based_translate(question)


def _llm_translate(question: str, catalog: DataCatalog) -> str | None:
    """Use Claude to generate SQL from natural language."""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed, falling back to rule-based")
        return _rule_based_translate(question)

    schema = _build_schema_prompt(catalog)

    client = anthropic.Anthropic(api_key=_ANTHROPIC_KEY)
    start = time.monotonic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": question}],
        system=(
            "You are a SQL generator for DuckDB. "
            "Given the user's question, return ONLY a single SQL query. "
            "No explanation, no markdown, just the SQL.\n\n"
            f"{schema}\n\n"
            "Rules:\n"
            "- Use DuckDB SQL syntax\n"
            "- For time windows, use NOW() - INTERVAL 'N hours/minutes'\n"
            "- Default time window is 1 hour if not specified\n"
            "- Return at most 100 rows\n"
            "- Only query tables listed above\n"
        ),
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    sql = ""
    for block in response.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            sql = text.strip()
            if sql:
                break
    if not sql:
        logger.warning("llm_returned_no_text_blocks")
        return None

    # Basic safety: must be a SELECT
    if not sql.upper().startswith("SELECT"):
        logger.warning("llm_returned_non_select", sql=sql[:100])
        return None

    logger.info("llm_sql_generated", question=question[:80], elapsed_ms=elapsed_ms)
    return sql


def _rule_based_translate(question: str) -> str | None:
    """Fallback: simple pattern-based NL→SQL translation."""
    q = question.lower().strip()

    order_match = re.search(r"order\s+(ORD-[\w-]+)", question, re.IGNORECASE)
    if order_match:
        oid = order_match.group(1)
        return f"SELECT * FROM orders_v2 WHERE order_id = '{oid}'"  # nosec B608 - order IDs are regex-validated before interpolation

    if "revenue" in q or "total sales" in q:
        window = _extract_window(q)
        return (
            f"SELECT SUM(total_amount) as revenue "  # nosec B608 - window text comes from _extract_window's numeric allowlist
            f"FROM orders_v2 "
            f"WHERE status != 'cancelled' "
            f"AND created_at >= NOW() - INTERVAL '{window}'"
        )

    if "average order" in q or "avg order" in q or "aov" in q:
        window = _extract_window(q)
        return (
            f"SELECT AVG(total_amount) as avg_order_value "  # nosec B608 - window text comes from _extract_window's numeric allowlist
            f"FROM orders_v2 "
            f"WHERE status != 'cancelled' "
            f"AND created_at >= NOW() - INTERVAL '{window}'"
        )

    if "top" in q and "product" in q:
        limit = 5
        limit_match = re.search(r"top\s+(\d+)", q)
        if limit_match:
            limit = int(limit_match.group(1))
        return (
            f"SELECT name, category, price, stock_quantity "  # nosec B608 - limit is parsed as an integer from the question text
            f"FROM products_current "
            f"ORDER BY price DESC "
            f"LIMIT {limit}"
        )

    if "conversion" in q:
        window = _extract_window(q)
        return (
            f"SELECT "  # nosec B608 - window text comes from _extract_window's numeric allowlist
            f"COUNT(*) FILTER (WHERE is_conversion) as conversions, "
            f"COUNT(*) as total_sessions, "
            f"ROUND(COUNT(*) FILTER (WHERE is_conversion)::FLOAT "
            f"/ NULLIF(COUNT(*), 0) * 100, 2) as conversion_pct "
            f"FROM sessions_aggregated "
            f"WHERE started_at >= NOW() - INTERVAL '{window}'"
        )

    if "user" in q:
        user_match = re.search(r"(USR-\d+)", question)
        if user_match:
            uid = user_match.group(1)
            return f"SELECT * FROM users_enriched WHERE user_id = '{uid}'"  # nosec B608 - user IDs are regex-validated before interpolation

    if "out of stock" in q or "stock" in q:
        return (
            "SELECT product_id, name, category, stock_quantity "
            "FROM products_current "
            "WHERE in_stock = FALSE OR stock_quantity = 0"
        )

    if "session" in q and ("active" in q or "current" in q):
        return (
            "SELECT COUNT(*) as active_sessions "
            "FROM sessions_aggregated "
            "WHERE ended_at IS NULL "
            "OR ended_at >= NOW() - INTERVAL '30 minutes'"
        )

    return None


def _extract_window(question: str) -> str:
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
    return "1 hour"
