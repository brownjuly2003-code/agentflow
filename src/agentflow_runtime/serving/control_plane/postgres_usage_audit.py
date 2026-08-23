"""Usage/audit repository of the PostgreSQL control-plane adapter.

API usage accounting (batched via ``executemany``) and the API session
analytics — the ``UsageAuditRepository`` capability surface (audit F-08
split; bodies verbatim from the pre-split ``postgres.py``).
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence

import structlog

from .postgres_base import _TRANSIENT_ERRORS, PostgresControlPlaneBase, _masked_dsn
from .store import UsageRow

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

try:
    import psycopg_pool
except ImportError:  # pragma: no cover
    psycopg_pool = None  # type: ignore[assignment]

logger = structlog.get_logger()


def _window_to_interval(window: str) -> str:
    # Same grammar as the embedded adapter's parser; the '<n> minutes/hours/
    # days' strings it produces are valid PostgreSQL interval literals too,
    # but parsing here (rather than passing user input through) keeps the
    # ValueError contract for malformed windows.
    match = re.fullmatch(r"(\d+)([mhd])", window.strip())
    if match is None:
        raise ValueError("Invalid window. Use formats like 15m, 1h, or 7d.")
    value, unit = match.groups()
    if unit == "m":
        return f"{value} minutes"
    if unit == "h":
        return f"{value} hours"
    return f"{value} days"


class PostgresUsageAuditRepository(PostgresControlPlaneBase):
    """``UsageAuditRepository`` capability of the PostgreSQL adapter."""

    # --- API usage accounting -------------------------------------------------

    def ensure_usage_schema(self) -> None:
        self._ensure_schema()

    def record_api_usage(
        self,
        *,
        tenant: str,
        key_name: str,
        endpoint: str,
        key_id: str | None,
        key_slot: str,
    ) -> None:
        # Bounded retry on transient connection errors, then raise — the
        # caller (record_usage) skips its audit publish on failure, exactly
        # like the embedded adapter's file-lock retry loop.
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO api_usage (tenant, key_name, endpoint, key_id, key_slot)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (tenant, key_name, endpoint, key_id, key_slot),
                    )
                return
            except _TRANSIENT_ERRORS as exc:
                last_error = exc
                time.sleep(0.01 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def record_api_usage_batch(self, rows: Sequence[UsageRow]) -> None:
        # One checkout, one executemany, ONE transaction (audit P1-1): the
        # base-class fallback of per-row record_api_usage calls would cost a
        # checkout and a commit per row — a 256-row batch was up to 256
        # connections on the pre-pool shape. psycopg batches the executemany
        # into pipelined server round trips inside the single transaction the
        # connection context manager owns, so the batch lands atomically:
        # every row shares one xmin, and a failed batch persists nothing.
        # Same failure contract as record_api_usage — raise after bounded
        # retries; the caller drops the batch and counts it.
        if not rows:
            return
        params = [
            (row.tenant, row.key_name, row.endpoint, row.key_id, row.key_slot) for row in rows
        ]
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._connect() as conn, conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO api_usage (tenant, key_name, endpoint, key_id, key_slot)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        params,
                    )
                return
            except _TRANSIENT_ERRORS as exc:
                last_error = exc
                time.sleep(0.01 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def get_usage_by_tenant(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tenant, COUNT(*) AS requests_last_24h
                FROM api_usage
                WHERE ts >= now() - INTERVAL '24 hours'
                GROUP BY tenant
                ORDER BY tenant
                """
            ).fetchall()
        return [
            {"tenant": tenant, "requests_last_24h": int(requests_last_24h)}
            for tenant, requests_last_24h in rows
        ]

    def get_usage_by_key(self) -> dict[tuple[str, str], int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tenant, key_name, COUNT(*) AS requests_last_24h
                FROM api_usage
                WHERE ts >= now() - INTERVAL '24 hours'
                GROUP BY tenant, key_name
                """
            ).fetchall()
        return {
            (tenant, key_name): int(requests_last_24h)
            for tenant, key_name, requests_last_24h in rows
        }

    def get_old_key_usage_by_key_id(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key_id, COUNT(*) AS requests_last_hour
                FROM api_usage
                WHERE key_slot = 'previous'
                  AND ts >= now() - INTERVAL '1 hour'
                  AND key_id IS NOT NULL
                GROUP BY key_id
                """
            ).fetchall()
        return {key_id: int(count) for key_id, count in rows}

    # --- API session analytics ------------------------------------------------

    def record_api_session(self, request_id: str, record: dict) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO api_sessions (
                        request_id, tenant, key_name, endpoint, method, status_code,
                        duration_ms, cache_hit, entity_type, entity_id, metric_name,
                        query_engine, query_text
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (request_id) DO UPDATE SET
                        tenant = EXCLUDED.tenant,
                        key_name = EXCLUDED.key_name,
                        endpoint = EXCLUDED.endpoint,
                        method = EXCLUDED.method,
                        status_code = EXCLUDED.status_code,
                        duration_ms = EXCLUDED.duration_ms,
                        cache_hit = EXCLUDED.cache_hit,
                        entity_type = EXCLUDED.entity_type,
                        entity_id = EXCLUDED.entity_id,
                        metric_name = EXCLUDED.metric_name,
                        query_engine = EXCLUDED.query_engine,
                        query_text = EXCLUDED.query_text
                    """,
                    (
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
                    ),
                )
        except psycopg.Error as exc:
            # Best-effort telemetry, same contract as the embedded adapter:
            # log and return rather than failing the request path.
            logger.warning(
                "analytics_session_write_skipped",
                stage="insert",
                dsn=_masked_dsn(self._dsn),
                request_id=request_id,
                tenant=record.get("tenant"),
                endpoint=record.get("endpoint"),
                error=str(exc),
                exc_info=True,
            )

    def get_usage_analytics(self, *, window: str = "24h", tenant: str | None = None) -> dict:
        interval = _window_to_interval(window)
        # Two literal SQL branches instead of an interpolated tenant clause —
        # the same shape as the embedded adapter.
        select_head = (
            "SELECT tenant, COUNT(*) AS total_requests, "
            "ROUND(AVG(CASE WHEN status_code >= 400 THEN 1.0 ELSE 0.0 END), 4) AS error_rate, "
            "ROUND(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 4) AS cache_hit_rate, "
            "ROUND(AVG(duration_ms)::numeric, 3) AS avg_duration_ms "
            "FROM api_sessions "
            "WHERE tenant IS NOT NULL AND ts >= now() - CAST(%s AS INTERVAL) "
        )
        if tenant:
            tenants_sql = select_head + "AND tenant = %s GROUP BY tenant ORDER BY tenant"
            params: tuple = (interval, tenant)
        else:
            tenants_sql = select_head + "GROUP BY tenant ORDER BY tenant"
            params = (interval,)
        with self._connect() as conn:
            rows = conn.execute(tenants_sql, params).fetchall()
            tenants = []
            for tenant_name, total_requests, error_rate, cache_hit_rate, avg_duration_ms in rows:
                top_endpoints = conn.execute(
                    """
                    SELECT endpoint
                    FROM api_sessions
                    WHERE tenant = %s
                      AND ts >= now() - CAST(%s AS INTERVAL)
                    GROUP BY endpoint
                    ORDER BY COUNT(*) DESC, endpoint
                    LIMIT 3
                    """,
                    (tenant_name, interval),
                ).fetchall()
                tenants.append(
                    {
                        "tenant": tenant_name,
                        "total_requests": int(total_requests),
                        "error_rate": float(error_rate or 0.0),
                        "cache_hit_rate": float(cache_hit_rate or 0.0),
                        "top_endpoints": [item[0] for item in top_endpoints],
                        "avg_duration_ms": float(avg_duration_ms or 0.0),
                    }
                )
        return {"window": window, "tenants": tenants}

    def get_top_queries(self, *, limit: int = 10, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT query_text, COUNT(*) AS frequency
                FROM api_sessions
                WHERE query_text IS NOT NULL
                  AND ts >= now() - CAST(%s AS INTERVAL)
                GROUP BY query_text
                ORDER BY frequency DESC, query_text
                LIMIT %s
                """,
                (interval, limit),
            ).fetchall()
        return {
            "window": window,
            "queries": [
                {"query": query_text, "count": int(frequency)} for query_text, frequency in rows
            ],
        }

    def get_top_entities(self, *, limit: int = 10, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT entity_type, entity_id, COUNT(*) AS frequency
                FROM api_sessions
                WHERE entity_id IS NOT NULL
                  AND ts >= now() - CAST(%s AS INTERVAL)
                GROUP BY entity_type, entity_id
                ORDER BY frequency DESC, entity_type, entity_id
                LIMIT %s
                """,
                (interval, limit),
            ).fetchall()
        return {
            "window": window,
            "entities": [
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "count": int(frequency),
                }
                for entity_type, entity_id, frequency in rows
            ],
        }

    def get_latency_analytics(self, *, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    endpoint,
                    COUNT(*) AS requests,
                    ROUND((percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms))::numeric,
                          3) AS p50_ms,
                    ROUND((percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms))::numeric,
                          3) AS p95_ms,
                    ROUND((percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms))::numeric,
                          3) AS p99_ms
                FROM api_sessions
                WHERE ts >= now() - CAST(%s AS INTERVAL)
                GROUP BY endpoint
                ORDER BY endpoint
                """,
                (interval,),
            ).fetchall()
        return {
            "window": window,
            "endpoints": [
                {
                    "endpoint": endpoint,
                    "requests": int(requests),
                    "p50_ms": float(p50_ms or 0.0),
                    "p95_ms": float(p95_ms or 0.0),
                    "p99_ms": float(p99_ms or 0.0),
                }
                for endpoint, requests, p50_ms, p95_ms, p99_ms in rows
            ],
        }

    def get_anomalies(self, *, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        with self._connect() as conn:
            rows = conn.execute(
                """
                WITH hourly AS (
                    SELECT
                        tenant,
                        date_trunc('hour', ts) AS hour_bucket,
                        COUNT(*) AS requests
                    FROM api_sessions
                    WHERE tenant IS NOT NULL
                      AND ts >= now() - CAST(%s AS INTERVAL)
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
                (interval,),
            ).fetchall()
        return {
            "window": window,
            "anomalies": [
                {
                    "tenant": tenant,
                    "current_hour_requests": int(current_hour_requests),
                    "hourly_average": float(hourly_average or 0.0),
                    "spike_ratio": float(spike_ratio or 0.0),
                }
                for tenant, current_hour_requests, hourly_average, spike_ratio in rows
            ],
        }

    def get_queries_per_second_last_minute(self) -> float:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM api_sessions
                    WHERE ts >= now() - INTERVAL '1 minute'
                    """
                ).fetchone()
        except psycopg.Error:
            # Same degrade-to-zero contract as the embedded adapter's
            # duckdb.Error guard: the admin tile shows 0.0 over failing.
            return 0.0
        requests_last_minute = row[0] if row else 0
        return round(float(requests_last_minute) / 60.0, 2)
