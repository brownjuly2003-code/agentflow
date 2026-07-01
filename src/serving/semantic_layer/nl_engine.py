"""LLM-powered NL→SQL engine via the GraceKelly orchestration API.

Translates natural language agent queries into SQL using the semantic catalog
as schema context. Falls back to rule-based patterns when GraceKelly is not
configured.

The LLM path does NOT call any model provider (Anthropic/OpenAI) directly — it
routes through GraceKelly's `/api/v1/orchestrate` endpoint, which owns model
selection and execution (browser-backed Sonnet 5). Set GRACEKELLY_URL to enable
LLM mode; the target model is GRACEKELLY_NL_SQL_MODEL (default claude-sonnet-5).

NOTE: the GraceKelly model registry must actually expose the requested model.
At time of writing GraceKelly ships `claude-sonnet-4-6`; `claude-sonnet-5`
becomes reachable only once GraceKelly itself is upgraded (tracked separately).
"""

import os
import re
import time

import structlog

from src.serving.semantic_layer.catalog import DataCatalog

logger = structlog.get_logger()

# GraceKelly V2 orchestration API (multi-model, browser-backed). The LLM NL→SQL
# path posts to `${GRACEKELLY_URL}/api/v1/orchestrate`. Empty => LLM disabled and
# the rule-based fallback is used.
_GRACEKELLY_URL = os.getenv("GRACEKELLY_URL", "")
_GK_NL_SQL_MODEL = os.getenv("GRACEKELLY_NL_SQL_MODEL", "claude-sonnet-5")
_GK_TIMEOUT_SECONDS = float(os.getenv("GRACEKELLY_TIMEOUT_SECONDS", "60"))


def _sql_str_literal(value: str) -> str:
    """Render ``value`` as a SQL string literal with single quotes doubled.

    Defense-in-depth for the rule-based fallback (audit A-4). The extraction
    regexes already exclude quote characters from the interpolated tokens, but
    quoting at the splice point keeps these sites inert even if a future edit
    loosens a pattern — the surface the report flagged as "one careless edit
    away from a hole". Mirrors ``SQLBuilderMixin._quote_literal`` for ``str``.
    """
    return "'" + value.replace("'", "''") + "'"


def _build_schema_prompt(catalog: DataCatalog) -> str:
    """Build a schema description for the LLM from the catalog."""
    lines = ["Available tables and columns:\n"]
    for name, entity in catalog.entities.items():
        fields = ", ".join(f"{f} ({desc})" for f, desc in entity.fields.items())
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

    Routes through GraceKelly (Sonnet 5) if GRACEKELLY_URL is set, otherwise
    falls back to rule-based patterns.
    """
    if _GRACEKELLY_URL:
        return _llm_translate(question, catalog)
    return _rule_based_translate(question)


def _llm_translate(question: str, catalog: DataCatalog) -> str | None:
    """Generate SQL via GraceKelly's orchestration API (Sonnet 5, single-model).

    Posts the schema-grounded prompt to `${GRACEKELLY_URL}/api/v1/orchestrate`
    with the target model and reads ``output_text`` from the returned task
    snapshot. GraceKelly owns provider/model execution — this function never
    talks to a model API directly. Any transport/HTTP failure returns ``None``
    so the caller degrades gracefully (the query package treats ``None`` as
    "untranslatable").
    """
    try:
        import httpx
    except ImportError:
        logger.warning("httpx_not_installed_falling_back", path="nl_llm")
        return _rule_based_translate(question)

    schema = _build_schema_prompt(catalog)
    prompt = (
        "You are a SQL generator for DuckDB. Given the user's question, return "
        "ONLY a single SQL query. No explanation, no markdown, just the SQL.\n\n"
        f"{schema}\n\n"
        "Rules:\n"
        "- Use DuckDB SQL syntax\n"
        "- For time windows, use NOW() - INTERVAL 'N hours/minutes'\n"
        "- Default time window is 1 hour if not specified\n"
        "- Return at most 100 rows\n"
        "- Only query tables listed above\n\n"
        f"Question: {question}"
    )

    start = time.monotonic()
    try:
        response = httpx.post(
            f"{_GRACEKELLY_URL.rstrip('/')}/api/v1/orchestrate",
            json={"prompt": prompt, "model": _GK_NL_SQL_MODEL},
            timeout=_GK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("gracekelly_request_failed", error=str(exc), model=_GK_NL_SQL_MODEL)
        return None

    elapsed_ms = int((time.monotonic() - start) * 1000)
    try:
        output = (response.json().get("output_text") or "").strip()
    except ValueError:
        logger.warning("gracekelly_non_json_response")
        return None

    sql = _strip_sql_fence(output)
    if not sql:
        logger.warning("gracekelly_returned_no_sql")
        return None

    # Basic safety: must be a SELECT
    if not sql.upper().startswith("SELECT"):
        logger.warning("gracekelly_returned_non_select", sql=sql[:100])
        return None

    logger.info(
        "gracekelly_sql_generated",
        question=question[:80],
        model=_GK_NL_SQL_MODEL,
        elapsed_ms=elapsed_ms,
    )
    return sql


def _strip_sql_fence(text: str) -> str:
    """Strip a leading/trailing markdown code fence GraceKelly may add.

    Browser-routed output can arrive wrapped in ```sql ... ``` despite the
    "no markdown" instruction; unwrap it so the SELECT check sees raw SQL.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def _rule_based_translate(question: str) -> str | None:
    """Fallback: simple pattern-based NL→SQL translation."""
    q = question.lower().strip()

    order_match = re.search(r"order\s+(ORD-[\w-]+)", question, re.IGNORECASE)
    if order_match:
        oid = order_match.group(1)
        # order IDs are regex-validated and quoted before interpolation
        return f"SELECT * FROM orders_v2 WHERE order_id = {_sql_str_literal(oid)}"  # nosec B608

    if "revenue" in q or "total sales" in q:
        window = _extract_window(q)
        return (
            # window text comes from _extract_window's numeric allowlist
            f"SELECT SUM(total_amount) as revenue "  # nosec B608
            f"FROM orders_v2 "
            f"WHERE status != 'cancelled' "
            f"AND created_at >= NOW() - INTERVAL {_sql_str_literal(window)}"
        )

    if "average order" in q or "avg order" in q or "aov" in q:
        window = _extract_window(q)
        return (
            # window text comes from _extract_window's numeric allowlist
            f"SELECT AVG(total_amount) as avg_order_value "  # nosec B608
            f"FROM orders_v2 "
            f"WHERE status != 'cancelled' "
            f"AND created_at >= NOW() - INTERVAL {_sql_str_literal(window)}"
        )

    if "top" in q and "product" in q:
        limit = 5
        limit_match = re.search(r"top\s+(\d+)", q)
        if limit_match:
            limit = int(limit_match.group(1))
        return (
            # limit is parsed as an integer from the question text
            f"SELECT name, category, price, stock_quantity "  # nosec B608
            f"FROM products_current "
            f"ORDER BY price DESC "
            f"LIMIT {limit}"
        )

    if "conversion" in q:
        window = _extract_window(q)
        return (
            # window text comes from _extract_window's numeric allowlist
            f"SELECT "  # nosec B608
            f"COUNT(*) FILTER (WHERE is_conversion) as conversions, "
            f"COUNT(*) as total_sessions, "
            f"ROUND(COUNT(*) FILTER (WHERE is_conversion)::FLOAT "
            f"/ NULLIF(COUNT(*), 0) * 100, 2) as conversion_pct "
            f"FROM sessions_aggregated "
            f"WHERE started_at >= NOW() - INTERVAL {_sql_str_literal(window)}"
        )

    if "user" in q:
        user_match = re.search(r"(USR-\d+)", question)
        if user_match:
            uid = user_match.group(1)
            # user IDs are regex-validated and quoted before interpolation
            return f"SELECT * FROM users_enriched WHERE user_id = {_sql_str_literal(uid)}"  # nosec B608

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
