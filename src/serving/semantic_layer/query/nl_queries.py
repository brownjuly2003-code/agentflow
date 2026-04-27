from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import time
from contextlib import nullcontext

from fastapi import HTTPException
from opentelemetry import trace

from src.processing.tracing import telemetry_disabled
from src.serving.backends import BackendExecutionError

from .contracts import NLQueryHost
from .sql_guard import UnsafeSQLError, validate_nl_sql

tracer = trace.get_tracer("agentflow.query_engine")


class UnsafeNLQueryError(HTTPException, ValueError):
    def __init__(self, detail: str) -> None:
        HTTPException.__init__(self, status_code=403, detail=detail)


def _default_allowed_tables(self: NLQueryHost) -> set[str]:
    allowed_tables = {entity.table for entity in self.catalog.entities.values()}
    allowed_tables.add("pipeline_events")
    return allowed_tables


def _prepare_nl_sql(translated_sql: str, allowed_tables: set[str]) -> str:
    try:
        validate_nl_sql(translated_sql, allowed_tables)
    except UnsafeSQLError as e:
        raise UnsafeNLQueryError(f"NL-to-SQL produced unsafe query: {e}") from e
    return translated_sql


class NLQueryMixin:
    def _translate_question_to_sql(
        self: NLQueryHost,
        question: str,
        tenant_id: str | None = None,
    ) -> str:
        from src.serving.semantic_layer.nl_engine import translate_nl_to_sql

        current_span = trace.get_current_span()
        translate_span = (
            nullcontext(current_span)
            if (
                not telemetry_disabled()
                and current_span.is_recording()
                and getattr(current_span, "name", "") == "query_engine.translate"
            )
            else (
                tracer.start_as_current_span("query_engine.translate")
                if not telemetry_disabled()
                else nullcontext()
            )
        )
        with translate_span as span:
            resolved_tenant_id = self._resolve_tenant_id(tenant_id)
            if span is not None and span.is_recording():
                span.set_attribute("question", question[:200])
                span.set_attribute(
                    "model",
                    "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "rule_based",
                )
                if resolved_tenant_id is not None:
                    span.set_attribute("tenant_id", resolved_tenant_id)

            sql = translate_nl_to_sql(question, self.catalog)
            if sql:
                return sql
            msg = (
                f"Could not translate question: '{question}'. "
                f"Try asking about: {list(self.catalog.entities.keys())} "
                f"or metrics: {list(self.catalog.metrics.keys())}"
            )
            raise ValueError(msg)

    def _build_query_hash(self, sql: str, tenant_id: str | None) -> str:
        return hashlib.sha256(f"{tenant_id or 'default'}:{sql}".encode()).hexdigest()

    def _encode_cursor(self, offset: int, query_hash: str) -> str:
        return base64.urlsafe_b64encode(f"{offset}:{query_hash}".encode()).decode()

    def _decode_cursor(self, cursor: str) -> tuple[int, str]:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            offset_text, query_hash = decoded.split(":", 1)
            offset = int(offset_text)
        except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise ValueError("Invalid cursor value.") from exc
        if offset < 0 or not query_hash:
            raise ValueError("Invalid cursor value.")
        return offset, query_hash

    def paginated_query(
        self: NLQueryHost,
        question: str,
        limit: int = 100,
        cursor: str | None = None,
        context: dict | None = None,
        tenant_id: str | None = None,
        allowed_tables: set[str] | list[str] | None = None,
    ) -> dict:
        """Execute a natural language query with cursor-based pagination."""
        del context

        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")

        start = time.monotonic()
        translated_sql = self._translate_question_to_sql(question, tenant_id=tenant_id)
        prepared_sql = _prepare_nl_sql(
            translated_sql,
            set(allowed_tables) if allowed_tables is not None else _default_allowed_tables(self),
        )
        sql = self._scope_sql(prepared_sql, tenant_id)
        query_hash = self._build_query_hash(sql, tenant_id)
        offset = 0
        if cursor is not None:
            offset, cursor_hash = self._decode_cursor(cursor)
            if cursor_hash != query_hash:
                raise ValueError("Cursor does not match the requested query.")

        page_query = (
            f"SELECT * FROM ({sql}) AS paginated_query "  # nosec B608 - sql is prevalidated by validate_nl_sql before pagination
            f"LIMIT {limit + 1} OFFSET {offset}"
        )
        count_query = (
            f"SELECT COUNT(*) FROM ("  # nosec B608 - sql is prevalidated by validate_nl_sql before pagination
            f"SELECT 1 FROM ({sql}) AS count_query LIMIT 10001"
            f") AS bounded_count"
        )

        try:
            query_span = (
                tracer.start_as_current_span(f"{self._backend_name}.query")
                if not telemetry_disabled()
                else nullcontext()
            )
            with query_span as span:
                resolved_tenant_id = self._resolve_tenant_id(tenant_id)
                if span is not None and span.is_recording():
                    span.set_attribute(
                        "sql",
                        sql[:200] if len(sql) <= 200 else f"{sql[:197]}...",
                    )
                    if resolved_tenant_id is not None:
                        span.set_attribute("tenant_id", resolved_tenant_id)
                page_rows = self._backend.execute(page_query)
                bounded_total = self._backend.scalar(count_query)
                if span is not None and span.is_recording():
                    span.set_attribute("row_count", len(page_rows[:limit]))
        except BackendExecutionError as e:
            raise ValueError(f"Query execution failed: {e}") from e

        has_more = len(page_rows) > limit
        data = page_rows[:limit]
        bounded_total = int(bounded_total) if bounded_total is not None else 0
        total_count = bounded_total if bounded_total <= 10_000 else None
        next_cursor = self._encode_cursor(offset + limit, query_hash) if has_more else None
        elapsed_ms = int((time.monotonic() - start) * 1000)

        return {
            "data": data,
            "sql": sql,
            "row_count": len(data),
            "total_count": total_count,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "page_size": limit,
            "execution_time_ms": elapsed_ms,
            "freshness_seconds": None,
        }

    def execute_nl_query(
        self: NLQueryHost,
        question: str,
        context: dict | None = None,
        tenant_id: str | None = None,
        allowed_tables: set[str] | list[str] | None = None,
    ) -> dict:
        """Translate a natural language question to SQL and execute it.

        Uses Claude API if ANTHROPIC_API_KEY is set, falls back to rule-based.
        """
        del context

        start = time.monotonic()
        translated_sql = self._translate_question_to_sql(question, tenant_id=tenant_id)
        prepared_sql = _prepare_nl_sql(
            translated_sql,
            set(allowed_tables) if allowed_tables is not None else _default_allowed_tables(self),
        )
        sql = self._scope_sql(prepared_sql, tenant_id)

        try:
            query_span = (
                tracer.start_as_current_span(f"{self._backend_name}.query")
                if not telemetry_disabled()
                else nullcontext()
            )
            with query_span as span:
                resolved_tenant_id = self._resolve_tenant_id(tenant_id)
                if span is not None and span.is_recording():
                    span.set_attribute(
                        "sql",
                        sql[:200] if len(sql) <= 200 else f"{sql[:197]}...",
                    )
                    if resolved_tenant_id is not None:
                        span.set_attribute("tenant_id", resolved_tenant_id)
                data = self._backend.execute(sql)
                if span is not None and span.is_recording():
                    span.set_attribute("row_count", len(data))
        except BackendExecutionError as e:
            raise ValueError(f"Query execution failed: {e}") from e

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return {
            "data": data,
            "sql": sql,
            "row_count": len(data),
            "execution_time_ms": elapsed_ms,
            "freshness_seconds": None,
        }

    def explain(
        self: NLQueryHost,
        question: str,
        tenant_id: str | None = None,
        allowed_tables: set[str] | list[str] | None = None,
    ) -> dict:
        """Translate a natural language question to SQL without executing it."""
        from src.serving.semantic_layer import nl_engine

        translated_sql = self._translate_question_to_sql(question, tenant_id=tenant_id)
        prepared_sql = _prepare_nl_sql(
            translated_sql,
            set(allowed_tables) if allowed_tables is not None else _default_allowed_tables(self),
        )
        sql = self._scope_sql(prepared_sql, tenant_id)

        engine = "rule_based"
        if getattr(nl_engine, "_ANTHROPIC_KEY", ""):
            try:
                import anthropic  # noqa: F401
            except ImportError:
                pass
            else:
                engine = "llm"

        try:
            explain_rows = self._backend.explain(sql)
        except BackendExecutionError as e:
            raise ValueError(f"Query explanation failed: {e}") from e

        plan = "\n".join(row[1] if len(row) > 1 else str(row[0]) for row in explain_rows)
        normalized_plan = re.sub(r"[â”‚â”Œâ”â””â”˜â”œâ”¤â”¬â”´â”€]", " ", plan)
        # Use sqlglot AST so tenant-quoted SQL still resolves to the
        # leaf table name (Codex review P2). Regex with FROM/JOIN +
        # bare identifier returned an empty list for quoted identifiers
        # like "acme"."orders_v2", dropping tables_accessed for tenant
        # explain calls.
        try:
            import sqlglot
            from sqlglot import exp as _exp

            parsed = sqlglot.parse_one(sql, read="duckdb")
            tables_accessed = list(
                dict.fromkeys(table.name for table in parsed.find_all(_exp.Table))
            )
        except Exception:
            tables_accessed = list(
                dict.fromkeys(
                    match.split(".")[-1]
                    for match in re.findall(
                        r"(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_\.]*)",
                        sql,
                        flags=re.IGNORECASE,
                    )
                )
            )
        row_estimates = [
            int(match.replace(",", ""))
            for match in re.findall(r"~\s*([0-9,]+)\s+row", normalized_plan)
        ]
        warning = None
        if tables_accessed and ("Sequential Scan" in plan or "SEQ_SCAN" in plan):
            warning = f"Full table scan on {tables_accessed[0]} (no index)"

        return {
            "question": question,
            "sql": sql,
            "tables_accessed": tables_accessed,
            "estimated_rows": max(row_estimates) if row_estimates else None,
            "engine": engine,
            "warning": warning,
        }
