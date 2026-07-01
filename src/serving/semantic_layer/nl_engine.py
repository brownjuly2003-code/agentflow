"""NL→SQL translation entrypoint for the serving layer.

Translates natural-language agent queries into SQL. Two modes:

- **Rule-based (shipped default).** Seven regex patterns → fixed SQL templates.
  Used whenever ``GRACEKELLY_URL`` is unset (every shipped demo config).
- **LLM (opt-in, ``GRACEKELLY_URL`` set).** Routes through the vendored NL_SQL
  generation engine (``nl_sql_engine``, ADR 0008): a LangGraph
  generate→validate→repair pipeline on **Claude Sonnet 5 via GraceKelly**,
  schema-grounded from the catalog. AgentFlow never calls a model provider
  (Anthropic/OpenAI) directly — GraceKelly owns model selection/execution behind
  ``/api/v1/orchestrate`` (browser-backed). Target model is
  ``GRACEKELLY_NL_SQL_MODEL`` (default ``claude-sonnet-5``), which GraceKelly
  serves today.

The engine is imported lazily on the LLM path so the rule-based default carries
no langgraph dependency. Either mode's output still passes through the serving
layer's DuckDB executor + ``sql_guard`` static validation (SELECT-only, no DML,
tenant-scoped) at query time.
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
    """Generate SQL through the vendored NL_SQL engine (Sonnet 5 via GraceKelly).

    Runs the LangGraph generate→validate→repair pipeline, schema-grounded from
    ``catalog``, on GraceKelly's ``/api/v1/orchestrate`` (this function never
    talks to a model API directly). Returns the validated SQL, or ``None`` when
    the engine is unavailable or the final candidate fails the static guard —
    the query package treats ``None`` as "untranslatable" and degrades.

    The engine is imported lazily so the rule-based default (the shipped path)
    never pulls in langgraph. If that import fails (e.g. langgraph/httpx not
    installed) we fall back to the rule-based translator rather than erroring.
    """
    try:
        from src.serving.semantic_layer.nl_sql_engine import (
            GraceKellyProvider,
            ProviderError,
            generate_sql_text,
        )
    except ImportError:
        logger.warning("nl_sql_engine_unavailable_falling_back", path="nl_llm")
        return _rule_based_translate(question)

    provider = GraceKellyProvider(
        model=_GK_NL_SQL_MODEL,
        base_url=_GRACEKELLY_URL,
        timeout_seconds=_GK_TIMEOUT_SECONDS,
    )
    start = time.monotonic()
    try:
        sql = generate_sql_text(question, catalog, provider=provider)
    except ProviderError as exc:
        logger.warning("gracekelly_request_failed", error=str(exc), model=_GK_NL_SQL_MODEL)
        return None

    elapsed_ms = int((time.monotonic() - start) * 1000)
    if not sql:
        logger.warning("gracekelly_returned_no_sql")
        return None

    logger.info(
        "gracekelly_sql_generated",
        question=question[:80],
        model=_GK_NL_SQL_MODEL,
        elapsed_ms=elapsed_ms,
    )
    return sql


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
