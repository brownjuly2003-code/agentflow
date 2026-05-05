import json
import os
import re
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

import duckdb
import structlog
from fastapi import Request
from starlette.background import BackgroundTasks
from starlette.responses import Response
from starlette.types import Message

from src.serving.duckdb_connection import connect_duckdb

logger = structlog.get_logger()


def ensure_analytics_table(db_path: Path | str) -> None:
    for attempt in range(10):
        try:
            conn = connect_duckdb(db_path)
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
            continue

        try:
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
            ):
                if column_name not in existing_columns:
                    conn.execute(f"ALTER TABLE api_sessions ADD COLUMN {column_name} {column_type}")
            return
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
        finally:
            conn.close()


def build_analytics_middleware():
    async def analytics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith("/v1"):
            return await call_next(request)
        auth_manager = getattr(request.app.state, "auth_manager", None)
        if auth_manager is None or not auth_manager.has_configured_keys():
            return await call_next(request)

        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        started_at = time.perf_counter()
        body = b""
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if body:

                async def receive() -> Message:
                    return {"type": "http.request", "body": body, "more_body": False}

                request._receive = receive

        try:
            response = await call_next(request)
        except Exception:  # nosec B110 - failure telemetry is best-effort before re-raising the original error
            # Record downstream failures before re-raising them through the client stack.
            _schedule_session_write(
                request.app.state.auth_manager.db_path,
                request_id,
                _build_session_record(
                    request=request,
                    request_id=request_id,
                    status_code=500,
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                    cache_hit=False,
                    body=body,
                ),
            )
            raise

        response.headers["X-Request-Id"] = request_id
        background = response.background
        if background is None:
            background = BackgroundTasks()
        elif not isinstance(background, BackgroundTasks):
            background = BackgroundTasks([background])
        background.add_task(
            _schedule_session_write,
            request.app.state.auth_manager.db_path,
            request_id,
            _build_session_record(
                request=request,
                request_id=request_id,
                status_code=response.status_code,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                cache_hit=response.headers.get("X-Cache") == "HIT",
                body=body,
            ),
        )
        response.background = background
        return response

    return analytics_middleware


def get_usage_analytics(
    db_path: Path | str,
    *,
    window: str = "24h",
    tenant: str | None = None,
) -> dict:
    interval = _window_to_interval(window)
    ensure_analytics_table(db_path)
    conn = connect_duckdb(db_path)
    try:
        if tenant:
            rows = conn.execute(
                """
                SELECT
                    tenant,
                    COUNT(*) AS total_requests,
                    ROUND(AVG(CASE WHEN status_code >= 400 THEN 1.0 ELSE 0.0 END), 4) AS error_rate,
                    ROUND(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 4) AS cache_hit_rate,
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
                    ROUND(AVG(CASE WHEN status_code >= 400 THEN 1.0 ELSE 0.0 END), 4) AS error_rate,
                    ROUND(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 4) AS cache_hit_rate,
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


def get_top_queries(
    db_path: Path | str,
    *,
    limit: int = 10,
    window: str = "24h",
) -> dict:
    interval = _window_to_interval(window)
    ensure_analytics_table(db_path)
    conn = connect_duckdb(db_path)
    try:
        rows = conn.execute(
            """
            SELECT query_text, COUNT(*) AS frequency
            FROM api_sessions
            WHERE query_text IS NOT NULL
              AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
            GROUP BY query_text
            ORDER BY frequency DESC, query_text
            LIMIT ?
            """,
            [interval, limit],
        ).fetchall()
        return {
            "window": window,
            "queries": [
                {"query": query_text, "count": frequency} for query_text, frequency in rows
            ],
        }
    finally:
        conn.close()


def get_top_entities(
    db_path: Path | str,
    *,
    limit: int = 10,
    window: str = "24h",
) -> dict:
    interval = _window_to_interval(window)
    ensure_analytics_table(db_path)
    conn = connect_duckdb(db_path)
    try:
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


def get_latency_analytics(
    db_path: Path | str,
    *,
    window: str = "24h",
) -> dict:
    interval = _window_to_interval(window)
    ensure_analytics_table(db_path)
    conn = connect_duckdb(db_path)
    try:
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


def get_anomalies(db_path: Path | str, *, window: str = "24h") -> dict:
    interval = _window_to_interval(window)
    ensure_analytics_table(db_path)
    conn = connect_duckdb(db_path)
    try:
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


def _schedule_session_write(db_path: Path | str, request_id: str, record: dict) -> None:
    threading.Thread(
        target=_insert_session,
        args=(db_path, request_id, record),
        daemon=True,
    ).start()


def _insert_session(db_path: Path | str, request_id: str, record: dict) -> None:
    for attempt in range(10):
        try:
            conn = connect_duckdb(db_path)
        except duckdb.Error as exc:
            if attempt == 9:
                logger.warning(
                    "analytics_session_write_skipped",
                    stage="connect",
                    db_path=str(db_path),
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
                    query_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ],
            )
            return
        except duckdb.Error as exc:
            if attempt == 9:
                logger.warning(
                    "analytics_session_write_skipped",
                    stage="insert",
                    db_path=str(db_path),
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


def _build_session_record(
    *,
    request: Request,
    request_id: str,
    status_code: int,
    duration_ms: float,
    cache_hit: bool,
    body: bytes,
) -> dict:
    tenant_key = getattr(request.state, "tenant_key", None)
    endpoint = request.url.path
    entity_type = None
    entity_id = None
    metric_name = None
    query_engine = None
    query_text = None
    parts = request.url.path.strip("/").split("/")

    if len(parts) >= 4 and parts[0] == "v1" and parts[1] == "entity":
        entity_type = parts[2]
        entity_id = parts[3]
        endpoint = f"/v1/entity/{entity_type}"
    elif len(parts) >= 3 and parts[0] == "v1" and parts[1] == "metrics":
        metric_name = parts[2]
        endpoint = f"/v1/metrics/{metric_name}"
    elif request.url.path == "/v1/query":
        query_engine = "llm" if os.getenv("ANTHROPIC_API_KEY") else "rule_based"
        if body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {}
            question = payload.get("question")
            if isinstance(question, str):
                query_text = question

    return {
        "request_id": request_id,
        "tenant": getattr(tenant_key, "tenant", None),
        "key_name": getattr(tenant_key, "name", None),
        "endpoint": endpoint,
        "method": request.method,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
        "cache_hit": cache_hit,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "metric_name": metric_name,
        "query_engine": query_engine,
        "query_text": query_text,
    }


def _window_to_interval(window: str) -> str:
    match = re.fullmatch(r"(\d+)([mhd])", window.strip())
    if match is None:
        raise ValueError("Invalid window. Use formats like 15m, 1h, or 7d.")
    value, unit = match.groups()
    if unit == "m":
        return f"{value} minutes"
    if unit == "h":
        return f"{value} hours"
    return f"{value} days"
