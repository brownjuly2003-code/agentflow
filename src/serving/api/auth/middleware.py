from __future__ import annotations

import os
import re
import secrets
from collections.abc import Awaitable, Callable
from typing import cast

import structlog
from fastapi import Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from src.constants import DEFAULT_RATE_LIMIT_WINDOW_SECONDS, FAILED_AUTH_WINDOW_SECONDS
from src.serving.api.metrics import AUTH_FAILURES
from src.serving.api.security import redact_sensitive_headers

from .manager import _CURRENT_TENANT_ID, TenantKey, get_auth_manager


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
        if _is_exempt_path(path):
            return await call_next(request)
        if not manager.has_configured_keys():
            # Fail closed unless the operator explicitly opted into open mode
            # for local development. Previous behaviour silently exposed every
            # non-admin route when the api_keys file was missing/empty
            # (Codex audit p2_1 #5, p2_2 #1).
            if os.getenv("AGENTFLOW_AUTH_DISABLED", "").strip().lower() in {
                "1",
                "true",
                "yes",
            } or getattr(request.app.state, "auth_disabled", False):
                return await call_next(request)
            AUTH_FAILURES.labels(reason="key_file_empty").inc()
            return JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "API key configuration is missing or empty. "
                        "Set AGENTFLOW_API_KEYS_FILE or AGENTFLOW_AUTH_DISABLED=true for local dev."
                    )
                },
            )

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
            AUTH_FAILURES.labels(reason="rate_limited").inc()
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
            if is_throttled:
                reason = "rate_limited"
            elif api_key == "":
                reason = "missing_key"
            else:
                reason = "invalid_key"
            AUTH_FAILURES.labels(reason=reason).inc()
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
    client_ip = _client_ip(request)
    if manager.is_failed_auth_limited(client_ip):
        AUTH_FAILURES.labels(reason="rate_limited").inc()
        raise HTTPException(
            status_code=429,
            detail="Too many failed authentication attempts from this IP.",
            headers={"Retry-After": str(FAILED_AUTH_WINDOW_SECONDS)},
        )
    if not manager.admin_key:
        AUTH_FAILURES.labels(reason="admin_unconfigured").inc()
        raise HTTPException(status_code=503, detail="Admin key is not configured.")
    if x_admin_key is None or not secrets.compare_digest(x_admin_key, manager.admin_key):
        manager.record_failed_auth(client_ip)
        AUTH_FAILURES.labels(reason="admin_invalid").inc()
        raise HTTPException(status_code=401, detail="Invalid or missing admin key.")
    manager.clear_failed_auth(client_ip)


def require_auth(request: Request) -> TenantKey:
    tenant_key = getattr(request.state, "tenant_key", None)
    if tenant_key is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    return cast(TenantKey, tenant_key)


def build_auth_middleware() -> AuthMiddleware:
    return AuthMiddleware()


def _is_exempt_path(path: str) -> bool:
    # `/metrics` is mounted as a sub-app; Starlette redirects bare `/metrics`
    # to `/metrics/`, so the trailing-slash variant must also be exempted or
    # Prometheus scrapes are rejected with 401.
    return (
        path.startswith("/docs")
        or path.startswith("/openapi")
        or path == "/metrics"
        or path.startswith("/metrics/")
        or path
        in {
            "/health",
            "/v1/health",
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
    # Honour X-Forwarded-For only when the immediate peer is a trusted proxy.
    # Without this gate any client could rotate failed-auth windows by spoofing
    # the header (Codex audit p2_2 #2).
    trusted = _trusted_proxies()
    peer_host = request.client.host if request.client is not None else None
    if trusted and peer_host in trusted:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
    return peer_host or "unknown"


def _trusted_proxies() -> frozenset[str]:
    raw = os.getenv("AGENTFLOW_TRUSTED_PROXIES", "").strip()
    if not raw:
        return frozenset()
    return frozenset(item.strip() for item in raw.split(",") if item.strip())
