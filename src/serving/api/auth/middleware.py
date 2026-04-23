from __future__ import annotations

import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import duckdb
import structlog
from fastapi import Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from src.constants import DEFAULT_RATE_LIMIT_WINDOW_SECONDS, FAILED_AUTH_WINDOW_SECONDS
from src.serving.api.security import redact_sensitive_headers

from .manager import _CURRENT_TENANT_ID, AuthManager, TenantKey, get_auth_manager


class AuthMiddleware:
    async def __call__(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        manager = get_auth_manager(request)
        path = request.url.path

        request.state.tenant_id = None
        if _is_admin_path(path):
            return await call_next(request)
        if _is_exempt_path(path) or not manager.has_configured_keys():
            return await call_next(request)

        client_ip = _client_ip(request)
        api_key = request.headers.get("X-API-Key", "")
        request_headers = redact_sensitive_headers(
            dict(request.headers),
            manager.security_policy.sensitive_headers_to_redact,
        )
        if manager.is_failed_auth_limited(client_ip):
            from src.serving.api import auth as auth_package

            auth_package.logger.warning(
                "api_auth_ip_throttled",
                client_ip=client_ip,
                path=path,
                headers=request_headers,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many failed authentication attempts from this IP."},
                headers={"Retry-After": str(FAILED_AUTH_WINDOW_SECONDS)},
            )

        tenant_key = manager.authenticate(api_key)
        if tenant_key is None:
            from src.serving.api import auth as auth_package

            is_throttled = manager.record_failed_auth(client_ip)
            auth_package.logger.warning(
                "api_auth_failed",
                client_ip=client_ip,
                path=path,
                headers=request_headers,
            )
            return JSONResponse(
                status_code=429 if is_throttled else 401,
                content={
                    "detail": (
                        "Too many failed authentication attempts from this IP."
                        if is_throttled
                        else "Invalid or missing API key. Pass X-API-Key header."
                    )
                },
                headers={"Retry-After": str(FAILED_AUTH_WINDOW_SECONDS)} if is_throttled else None,
            )

        manager.clear_failed_auth(client_ip)
        manager.record_usage(tenant_key, path)
        is_allowed, remaining, reset_at = await manager.check_rate_limit(tenant_key)
        rate_limit_headers = {
            "X-RateLimit-Limit": str(tenant_key.rate_limit_rpm),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_at),
        }

        if not is_allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (f"Rate limit exceeded: {tenant_key.rate_limit_rpm} requests/minute"),
                },
                headers={
                    "Retry-After": str(DEFAULT_RATE_LIMIT_WINDOW_SECONDS),
                    **rate_limit_headers,
                },
            )

        entity_type = _entity_type_from_path(path)
        if entity_type and not manager.is_entity_allowed(tenant_key, entity_type):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        f"API key '{tenant_key.name}' cannot access entity type '{entity_type}'."
                    ),
                },
                headers=rate_limit_headers,
            )

        request.state.tenant_key = tenant_key
        request.state.tenant_id = tenant_key.tenant
        structlog.contextvars.bind_contextvars(tenant_id=tenant_key.tenant)
        token = _CURRENT_TENANT_ID.set(tenant_key.tenant)
        try:
            response = await call_next(request)
        finally:
            _CURRENT_TENANT_ID.reset(token)
        for header, value in rate_limit_headers.items():
            response.headers[header] = value
        return response


def require_admin_key(
    request: Request,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    manager = get_auth_manager(request)
    if not manager.admin_key:
        raise HTTPException(status_code=503, detail="Admin key is not configured.")
    if x_admin_key is None or not secrets.compare_digest(x_admin_key, manager.admin_key):
        raise HTTPException(status_code=401, detail="Invalid or missing admin key.")


def require_auth(request: Request) -> TenantKey:
    tenant_key = getattr(request.state, "tenant_key", None)
    if tenant_key is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    return cast(TenantKey, tenant_key)


def build_auth_middleware() -> AuthMiddleware:
    return AuthMiddleware()


def ensure_usage_table(manager: AuthManager) -> None:
    for attempt in range(10):
        try:
            conn = duckdb.connect(str(manager.db_path))
        except duckdb.IOException as exc:
            if (
                os.getenv("AGENTFLOW_USAGE_DB_PATH") is None
                and manager.db_path.name == "agentflow_api.duckdb"
            ):
                from src.serving.api import auth as auth_package

                fallback_path = (
                    Path(os.getenv("TEMP", "."))
                    / f"agentflow_api_{os.getpid()}_{time.time_ns()}.duckdb"
                )
                auth_package.logger.warning(
                    "usage_db_path_fallback",
                    original=str(manager.db_path),
                    fallback=str(fallback_path),
                    error=str(exc),
                )
                manager.db_path = fallback_path
                conn = duckdb.connect(str(manager.db_path))
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
            return
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
        finally:
            conn.close()


def record_usage(manager: AuthManager, tenant_key: TenantKey, endpoint: str) -> None:
    for attempt in range(10):
        try:
            conn = duckdb.connect(str(manager.db_path))
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
                [
                    tenant_key.tenant,
                    tenant_key.name,
                    endpoint,
                    tenant_key.key_id,
                    tenant_key.matched_slot,
                ],
            )
            return
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
        finally:
            conn.close()


def usage_by_tenant(manager: AuthManager) -> list[dict]:
    conn = duckdb.connect(str(manager.db_path))
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


def _is_exempt_path(path: str) -> bool:
    return (
        path.startswith("/docs")
        or path.startswith("/openapi")
        or path
        in {
            "/health",
            "/v1/health",
            "/metrics",
        }
    )


def _is_admin_path(path: str) -> bool:
    return path.startswith("/v1/admin") or path.startswith("/admin")


def _entity_type_from_path(path: str) -> str | None:
    match = re.match(r"^/v1/entity/([^/]+)/", path)
    if match:
        return match.group(1)
    return None


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client is not None else "unknown"
