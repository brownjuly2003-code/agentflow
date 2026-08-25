"""Usage/audit repository of the embedded (DuckDB) control-plane adapter.

API usage accounting and the API session analytics — the
``UsageAuditRepository`` capability surface (audit F-08 split; bodies
verbatim from the pre-split ``embedded.py``).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Sequence
from pathlib import Path

import duckdb
import structlog

from .embedded_base import EmbeddedControlPlaneBase
from .store import UsageRow

logger = structlog.get_logger()


def ensure_api_usage_table(conn: duckdb.DuckDBPyConnection) -> None:
    # Moved verbatim from auth/usage_table.py in ADR 0010 slice 4. Runs on a
    # dedicated per-call connection (never the shared query_engine conn — see
    # the store module docstring), so unlike its ensure_* siblings above it
    # needs no catalog_ddl_lock.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage (
            tenant TEXT,
            key_name TEXT,
            endpoint TEXT,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info('api_usage')").fetchall()}
    if "key_id" not in columns:
        conn.execute("ALTER TABLE api_usage ADD COLUMN key_id TEXT")
    if "key_slot" not in columns:
        conn.execute("ALTER TABLE api_usage ADD COLUMN key_slot TEXT")


def ensure_api_sessions_table(conn: duckdb.DuckDBPyConnection) -> None:
    # Moved verbatim from api/analytics.py in ADR 0010 slice 4 (that module's
    # own path-based `ensure_analytics_table` stays put — it is independently
    # pinned by main.py's boot call and a middleware test's monkeypatch — so
    # this is a second, conn-based copy for the store's own methods).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_sessions (
            request_id TEXT PRIMARY KEY,
            tenant TEXT,
            key_name TEXT,
            endpoint TEXT,
            method TEXT,
            status_code INTEGER,
            duration_ms FLOAT,
            cache_hit BOOLEAN,
            entity_type TEXT,
            metric_name TEXT,
            query_engine TEXT,
            ts TIMESTAMP DEFAULT NOW()
        )
        """
    )
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('api_sessions')").fetchall()
    }
    for column_name, column_type in (
        ("entity_id", "TEXT"),
        ("query_text", "TEXT"),
        # Peppered digest of the question (audit F-18): the default analytics
        # record keeps this instead of the question itself.
        ("query_fingerprint", "TEXT"),
    ):
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE api_sessions ADD COLUMN {column_name} {column_type}")


def _window_to_interval(window: str) -> str:
    # Moved verbatim from api/analytics.py in ADR 0010 slice 4 — DuckDB
    # interval-literal syntax is an adapter detail; a future PostgreSQL
    # adapter parses `window` into its own interval syntax.
    match = re.fullmatch(r"(\d+)([mhd])", window.strip())
    if match is None:
        raise ValueError("Invalid window. Use formats like 15m, 1h, or 7d.")
    value, unit = match.groups()
    if unit == "m":
        return f"{value} minutes"
    if unit == "h":
        return f"{value} hours"
    return f"{value} days"


class EmbeddedUsageAuditRepository(EmbeddedControlPlaneBase):
    """``UsageAuditRepository`` capability of the embedded adapter."""

    def ensure_usage_schema(self) -> None:
        # Moved verbatim from auth/usage_table.py's ensure_usage_table
        # (ADR 0010 slice 4), including the Windows file-lock fallback: if
        # the configured usage db path can't be opened, fall back to a
        # per-process temp file and stick with it for this store's lifetime.
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.IOException as exc:
                if (
                    os.getenv("AGENTFLOW_USAGE_DB_PATH") is None
                    and self._usage_db_path.name == "agentflow_api.duckdb"
                ):
                    fallback_path = (
                        Path(os.getenv("TEMP", "."))
                        / f"agentflow_api_{os.getpid()}_{time.time_ns()}.duckdb"
                    )
                    logger.warning(
                        "usage_db_path_fallback",
                        original=str(self._usage_db_path),
                        fallback=str(fallback_path),
                        error=str(exc),
                    )
                    self._usage_db_path_override = fallback_path
                    conn = self._usage_cursor()
                else:
                    if attempt == 9:
                        raise
                    time.sleep(0.01 * (attempt + 1))
                    continue
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                ensure_api_usage_table(conn)
                return
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()

    def record_api_usage(
        self,
        *,
        tenant: str,
        key_name: str,
        endpoint: str,
        key_id: str | None,
        key_slot: str,
    ) -> None:
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                conn.execute(
                    """
                    INSERT INTO api_usage (tenant, key_name, endpoint, key_id, key_slot)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [tenant, key_name, endpoint, key_id, key_slot],
                )
                return
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()

    def record_api_usage_batch(self, rows: Sequence[UsageRow]) -> None:
        """One ``executemany`` inside one transaction, so a batch of N rows
        costs one commit rather than N.

        DuckDB serializes writers, so the per-row form put a commit — an fsync
        — on the critical path of every authenticated request, capping the API
        at ``1 / commit_latency`` requests per second. Batching lifts the
        accounting ceiling to ``len(rows) / commit_latency``, which is what
        lets the writer keep up with the request rate off the request path
        (docs/perf/usage-write-bifurcation-2026-07-09.md).
        """
        if not rows:
            return
        params = [[r.tenant, r.key_name, r.endpoint, r.key_id, r.key_slot] for r in rows]
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                conn.execute("BEGIN TRANSACTION")
                try:
                    conn.executemany(
                        """
                        INSERT INTO api_usage (tenant, key_name, endpoint, key_id, key_slot)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        params,
                    )
                except duckdb.Error:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
                return
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()

    def get_usage_by_tenant(self) -> list[dict]:
        conn = self._usage_cursor()
        try:
            rows = conn.execute(
                """
                SELECT tenant, COUNT(*) AS requests_last_24h
                FROM api_usage
                WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                GROUP BY tenant
                ORDER BY tenant
                """
            ).fetchall()
        finally:
            conn.close()
        return [
            {"tenant": tenant, "requests_last_24h": requests_last_24h}
            for tenant, requests_last_24h in rows
        ]

    def get_usage_by_key(self) -> dict[tuple[str, str], int]:
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                rows = conn.execute(
                    """
                    SELECT tenant, key_name, COUNT(*) AS requests_last_24h
                    FROM api_usage
                    WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                    GROUP BY tenant, key_name
                    """
                ).fetchall()
                return {
                    (tenant, key_name): requests_last_24h
                    for tenant, key_name, requests_last_24h in rows
                }
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()
        return {}

    def get_old_key_usage_by_key_id(self) -> dict[str, int]:
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                rows = conn.execute(
                    """
                    SELECT key_id, COUNT(*) AS requests_last_hour
                    FROM api_usage
                    WHERE key_slot = 'previous'
                      AND ts >= CURRENT_TIMESTAMP - INTERVAL '1 hour'
                      AND key_id IS NOT NULL
                    GROUP BY key_id
                    """
                ).fetchall()
                return dict(rows)
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()
        return {}

    # --- API session analytics ------------------------------------------------

    def record_api_session(self, request_id: str, record: dict) -> None:
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.Error as exc:
                if attempt == 9:
                    logger.warning(
                        "analytics_session_write_skipped",
                        stage="connect",
                        db_path=str(self._usage_db_path),
                        request_id=request_id,
                        tenant=record.get("tenant"),
                        endpoint=record.get("endpoint"),
                        attempts=attempt + 1,
                        error=str(exc),
                        exc_info=True,
                    )
                    return
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO api_sessions (
                        request_id,
                        tenant,
                        key_name,
                        endpoint,
                        method,
                        status_code,
                        duration_ms,
                        cache_hit,
                        entity_type,
                        entity_id,
                        metric_name,
                        query_engine,
                        query_text,
                        query_fingerprint
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        request_id,
                        record["tenant"],
                        record["key_name"],
                        record["endpoint"],
                        record["method"],
                        record["status_code"],
                        record["duration_ms"],
                        record["cache_hit"],
                        record["entity_type"],
                        record["entity_id"],
                        record["metric_name"],
                        record["query_engine"],
                        record["query_text"],
                        record.get("query_fingerprint"),
                    ],
                )
                return
            except duckdb.Error as exc:
                if attempt == 9:
                    logger.warning(
                        "analytics_session_write_skipped",
                        stage="insert",
                        db_path=str(self._usage_db_path),
                        request_id=request_id,
                        tenant=record.get("tenant"),
                        endpoint=record.get("endpoint"),
                        attempts=attempt + 1,
                        error=str(exc),
                        exc_info=True,
                    )
                    return
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()

    def get_usage_analytics(self, *, window: str = "24h", tenant: str | None = None) -> dict:
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            if tenant:
                rows = conn.execute(
                    """
                    SELECT
                        tenant,
                        COUNT(*) AS total_requests,
                        ROUND(AVG(CASE WHEN status_code >= 400 THEN 1.0 ELSE 0.0 END), 4)
                            AS error_rate,
                        ROUND(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 4)
                            AS cache_hit_rate,
                        ROUND(AVG(duration_ms), 3) AS avg_duration_ms
                    FROM api_sessions
                    WHERE tenant IS NOT NULL
                      AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                      AND tenant = ?
                    GROUP BY tenant
                    ORDER BY tenant
                    """,
                    [interval, tenant],
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT
                        tenant,
                        COUNT(*) AS total_requests,
                        ROUND(AVG(CASE WHEN status_code >= 400 THEN 1.0 ELSE 0.0 END), 4)
                            AS error_rate,
                        ROUND(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 4)
                            AS cache_hit_rate,
                        ROUND(AVG(duration_ms), 3) AS avg_duration_ms
                    FROM api_sessions
                    WHERE tenant IS NOT NULL
                      AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                    GROUP BY tenant
                    ORDER BY tenant
                    """,
                    [interval],
                ).fetchall()
            tenants = []
            for tenant_name, total_requests, error_rate, cache_hit_rate, avg_duration_ms in rows:
                top_endpoints = conn.execute(
                    """
                    SELECT endpoint
                    FROM api_sessions
                    WHERE tenant = ?
                      AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                    GROUP BY endpoint
                    ORDER BY COUNT(*) DESC, endpoint
                    LIMIT 3
                    """,
                    [tenant_name, interval],
                ).fetchall()
                tenants.append(
                    {
                        "tenant": tenant_name,
                        "total_requests": total_requests,
                        "error_rate": float(error_rate or 0.0),
                        "cache_hit_rate": float(cache_hit_rate or 0.0),
                        "top_endpoints": [item[0] for item in top_endpoints],
                        "avg_duration_ms": float(avg_duration_ms or 0.0),
                    }
                )
            return {"window": window, "tenants": tenants}
        finally:
            conn.close()

    def get_top_queries(self, *, limit: int = 10, window: str = "24h") -> dict:
        # Grouped by (text, fingerprint) rather than text alone (audit F-18):
        # the default policy stores no text, and grouping by a column that is
        # NULL for every row would report "no queries" for a busy API. The
        # fingerprint is deterministic per question, so the grouping is the
        # same one either way -- what changes is whether the caller can read
        # the question or only count its repeats.
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            rows = conn.execute(
                """
                SELECT query_text, query_fingerprint, COUNT(*) AS frequency
                FROM api_sessions
                WHERE (query_text IS NOT NULL OR query_fingerprint IS NOT NULL)
                  AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                GROUP BY query_text, query_fingerprint
                ORDER BY frequency DESC, query_fingerprint, query_text
                LIMIT ?
                """,
                [interval, limit],
            ).fetchall()
            return {
                "window": window,
                "queries": [
                    {
                        "query": query_text,
                        "fingerprint": query_fingerprint,
                        "count": frequency,
                    }
                    for query_text, query_fingerprint, frequency in rows
                ],
            }
        finally:
            conn.close()

    def prune_api_sessions(self, *, older_than_days: int) -> int:
        """Delete analytics rows past the retention window; return the count.

        Retention is a promise about the *oldest* row, so this deletes by `ts`
        and does not care whether a row carries a question, a fingerprint or
        neither.
        """
        if older_than_days < 1:
            raise ValueError(f"older_than_days must be at least 1, got {older_than_days}")
        interval = f"{older_than_days} days"
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM api_sessions
                WHERE ts < CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                """,
                [interval],
            ).fetchone()
            expired = int(row[0]) if row else 0
            if expired:
                conn.execute(
                    """
                    DELETE FROM api_sessions
                    WHERE ts < CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                    """,
                    [interval],
                )
            return int(expired)
        finally:
            conn.close()

    def delete_tenant_api_sessions(self, *, tenant: str) -> int:
        """Delete every analytics row for one tenant; return the count.

        An erasure request does not wait out the retention window, so this
        ignores `ts`. It stops at `api_sessions`: `api_usage` counters carry
        no user content and answer "how much did this tenant use", which a
        billing or abuse investigation still needs after the questions are
        gone (audit F-18).
        """
        if not tenant:
            raise ValueError("tenant must be a non-empty identifier")
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            row = conn.execute(
                "SELECT COUNT(*) FROM api_sessions WHERE tenant = ?",
                [tenant],
            ).fetchone()
            matched = int(row[0]) if row else 0
            if matched:
                conn.execute("DELETE FROM api_sessions WHERE tenant = ?", [tenant])
            return matched
        finally:
            conn.close()

    def get_top_entities(self, *, limit: int = 10, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            rows = conn.execute(
                """
                SELECT entity_type, entity_id, COUNT(*) AS frequency
                FROM api_sessions
                WHERE entity_id IS NOT NULL
                  AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                GROUP BY entity_type, entity_id
                ORDER BY frequency DESC, entity_type, entity_id
                LIMIT ?
                """,
                [interval, limit],
            ).fetchall()
            return {
                "window": window,
                "entities": [
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "count": frequency,
                    }
                    for entity_type, entity_id, frequency in rows
                ],
            }
        finally:
            conn.close()

    def get_latency_analytics(self, *, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            rows = conn.execute(
                """
                SELECT
                    endpoint,
                    COUNT(*) AS requests,
                    ROUND(quantile_cont(duration_ms, 0.50), 3) AS p50_ms,
                    ROUND(quantile_cont(duration_ms, 0.95), 3) AS p95_ms,
                    ROUND(quantile_cont(duration_ms, 0.99), 3) AS p99_ms
                FROM api_sessions
                WHERE ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                GROUP BY endpoint
                ORDER BY endpoint
                """,
                [interval],
            ).fetchall()
            return {
                "window": window,
                "endpoints": [
                    {
                        "endpoint": endpoint,
                        "requests": requests,
                        "p50_ms": float(p50_ms or 0.0),
                        "p95_ms": float(p95_ms or 0.0),
                        "p99_ms": float(p99_ms or 0.0),
                    }
                    for endpoint, requests, p50_ms, p95_ms, p99_ms in rows
                ],
            }
        finally:
            conn.close()

    def get_anomalies(self, *, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            rows = conn.execute(
                """
                WITH hourly AS (
                    SELECT
                        tenant,
                        date_trunc('hour', ts) AS hour_bucket,
                        COUNT(*) AS requests
                    FROM api_sessions
                    WHERE tenant IS NOT NULL
                      AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                    GROUP BY tenant, hour_bucket
                ),
                latest AS (
                    SELECT tenant, MAX(hour_bucket) AS current_hour
                    FROM hourly
                    GROUP BY tenant
                ),
                current_hour AS (
                    SELECT
                        hourly.tenant,
                        hourly.hour_bucket,
                        hourly.requests AS current_hour_requests
                    FROM hourly
                    JOIN latest
                      ON latest.tenant = hourly.tenant
                     AND latest.current_hour = hourly.hour_bucket
                ),
                historical AS (
                    SELECT
                        current_hour.tenant,
                        ROUND(AVG(hourly.requests), 1) AS hourly_average
                    FROM current_hour
                    JOIN hourly
                      ON hourly.tenant = current_hour.tenant
                     AND hourly.hour_bucket < current_hour.hour_bucket
                    GROUP BY current_hour.tenant
                ),
                scored AS (
                    SELECT
                        current_hour.tenant,
                        current_hour.current_hour_requests,
                        historical.hourly_average,
                        ROUND(
                            current_hour.current_hour_requests
                            / NULLIF(historical.hourly_average, 0),
                            2
                        ) AS spike_ratio
                    FROM current_hour
                    JOIN historical
                      ON historical.tenant = current_hour.tenant
                )
                SELECT tenant, current_hour_requests, hourly_average, spike_ratio
                FROM scored
                WHERE spike_ratio > 3
                ORDER BY spike_ratio DESC, tenant
                """,
                [interval],
            ).fetchall()
            return {
                "window": window,
                "anomalies": [
                    {
                        "tenant": tenant,
                        "current_hour_requests": current_hour_requests,
                        "hourly_average": float(hourly_average or 0.0),
                        "spike_ratio": float(spike_ratio or 0.0),
                    }
                    for tenant, current_hour_requests, hourly_average, spike_ratio in rows
                ],
            }
        finally:
            conn.close()

    def get_queries_per_second_last_minute(self) -> float:
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM api_sessions
                WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '1 minute'
                """
            ).fetchone()
            requests_last_minute = row[0] if row else 0
        except duckdb.Error:
            return 0.0
        finally:
            conn.close()
        return round(float(requests_last_minute) / 60.0, 2)
