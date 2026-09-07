from __future__ import annotations

import os
import re
import secrets
from collections.abc import Awaitable, Callable
from typing import cast

import structlog
from fastapi import Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from agentflow_runtime.constants import (
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    FAILED_AUTH_SCOPE_ADMIN,
    FAILED_AUTH_WINDOW_SECONDS,
)
from agentflow_runtime.serving.api.metrics import AUTH_FAILURES
from agentflow_runtime.serving.api.security import redact_sensitive_headers

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
        if _is_exempt_path(path):
            return await call_next(request)
        if not manager.has_configured_keys():
            # Fail closed unless the operator explicitly opted into open mode
            # for local development. Previous behaviour silently exposed every
            # non-admin route when the api_keys file was missing/empty
            # (audit p2_1 #5, p2_2 #1).
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
        # The throttle used to answer 429 before the key was looked at, which
        # made it a denial-of-service tool: behind a gateway without
        # AGENTFLOW_TRUSTED_PROXIES every caller shares one address, so eleven
        # requests with any junk key took the whole pod offline for an hour --
        # tenants and admins alike (audit FB-06). Resolve the key first; a
        # valid one always serves, and only a failure consults the window.
        # Under throttle the resolution is capped to the constant-work paths so
        # a scanner still cannot buy N bcrypt verifications per guess.
        throttled = manager.is_failed_auth_limited(client_ip)
        tenant_key = manager.authenticate(api_key, allow_legacy_scan=not throttled)
        if tenant_key is None:
            from agentflow_runtime.serving.api import auth as auth_package

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
        # Usage accounting is a side-channel: it may not fail the request it is
        # counting, and it may not pace it either. Writing the row here — even
        # offloaded to a worker thread — put a serialized DuckDB commit on the
        # critical path of every authenticated request, capping the API at
        # `1 / commit_latency` rps and tipping the CI load test into a
        # saturated equilibrium whenever the runner's disk was slow
        # (docs/perf/usage-write-bifurcation-2026-07-09.md).
        #
        # Hand the row to the writer thread and move on. A full queue sheds the
        # row and counts it; a failed write counts it too. Both counters are
        # what to alert on, never the client.
        if not manager.submit_usage(tenant_key, path):
            from agentflow_runtime.serving.api import auth as auth_package

            auth_package.logger.warning(
                "api_usage_record_skipped",
                tenant=tenant_key.tenant,
                key_name=tenant_key.name,
                path=path,
            )
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


def _log_admin_auth_failed(
    request: Request,
    manager: AuthManager,
    *,
    reason: str,
    client_ip: str,
    path: str,
) -> None:
    """Record an admin-surface refusal, never the credential that was tried.

    Headers go through the operator's redaction policy and then lose
    ``X-Admin-Key`` unconditionally. That policy list is operator-configurable
    (``config/security.yaml``) and audit F-11 already had to repair a built-in
    default that omitted the header; on the one credential every operator
    shares -- the one that issues, rotates and revokes every tenant key -- an
    audit line must not depend on that list still being right.
    """
    from agentflow_runtime.serving.api import auth as auth_package

    headers = redact_sensitive_headers(
        dict(request.headers),
        manager.security_policy.sensitive_headers_to_redact,
    )
    auth_package.logger.warning(
        "admin_auth_failed",
        reason=reason,
        client_ip=client_ip,
        path=path,
        headers={
            name: ("[REDACTED]" if name.lower() == "x-admin-key" else value)
            for name, value in headers.items()
        },
    )


def require_admin_key(
    request: Request,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    manager = get_auth_manager(request)
    client_ip = _client_ip(request)
    path = request.url.path
    # Every refusal on this surface leaves a structured line, not only a
    # counter (audit FB-10). `AUTH_FAILURES{reason=...}` says an admin refusal
    # happened somewhere in the deployment; it cannot say from which address,
    # against which route, or whether the 503 that woke someone at 03:00 was a
    # rotated Secret the Deployment never picked up. The tenant path has
    # logged `api_auth_failed` since F-11, which left the highest-privilege
    # credential in the system as the one surface with no audit trail.
    # `admin_auth_failed` is a separate event from `api_auth_failed` on
    # purpose: a scan against /v1 and someone guessing the operator key are
    # different incidents and want different detection rules.
    if not manager.admin_key:
        AUTH_FAILURES.labels(reason="admin_unconfigured").inc()
        _log_admin_auth_failed(
            request, manager, reason="admin_unconfigured", client_ip=client_ip, path=path
        )
        raise HTTPException(status_code=503, detail="Admin key is not configured.")
    # Checking the admin key is one constant-time comparison, so -- unlike the
    # tenant path -- there is no expensive work an early gate would be saving.
    # Check it first so a valid operator is never locked out by someone else's
    # guesses, and count failures in the admin scope so a scan against /v1
    # cannot throttle the surface used to answer it (audit FB-06).
    if x_admin_key is None or not _constant_time_equals(x_admin_key, manager.admin_key):
        is_throttled = manager.record_failed_auth(client_ip, scope=FAILED_AUTH_SCOPE_ADMIN)
        if is_throttled:
            AUTH_FAILURES.labels(reason="rate_limited").inc()
            _log_admin_auth_failed(
                request, manager, reason="rate_limited", client_ip=client_ip, path=path
            )
            raise HTTPException(
                status_code=429,
                detail="Too many failed authentication attempts from this IP.",
                headers={"Retry-After": str(FAILED_AUTH_WINDOW_SECONDS)},
            )
        AUTH_FAILURES.labels(reason="admin_invalid").inc()
        _log_admin_auth_failed(
            request, manager, reason="admin_invalid", client_ip=client_ip, path=path
        )
        raise HTTPException(status_code=401, detail="Invalid or missing admin key.")
    manager.clear_failed_auth(client_ip, scope=FAILED_AUTH_SCOPE_ADMIN)


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
            # Kubernetes probes and the Compose healthcheck carry no API key
            # (audit P0-3 split them out of the always-200 /v1/health).
            "/health/live",
            "/health/ready",
            "/v1/health",
            # Node federation ingest (ADR 0012) authenticates with its own
            # bearer node-token, not an X-API-Key; the endpoint does the check.
            "/v1/node/events",
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
    # the header (audit p2_2 #2).
    trusted = _trusted_proxies()
    peer_host = request.client.host if request.client is not None else None
    if trusted and peer_host in trusted:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            hops = [hop.strip() for hop in forwarded_for.split(",")]
            hops = [hop for hop in hops if hop]
            if hops:
                return _first_untrusted_hop(hops, trusted)
    return peer_host or "unknown"


def _first_untrusted_hop(hops: list[str], trusted: frozenset[str]) -> str:
    # X-Forwarded-For is append-only and each proxy writes the peer it actually
    # saw, so accountability decreases left to right: the LEFTMOST element is
    # whatever the first client sent, which a client may invent. Reading it was
    # how an attacker rotated the failed-auth window once per request while the
    # trusted-proxy gate was satisfied (audit FB-06). Walk from the right and
    # stop at the first hop that no configured proxy vouches for.
    for hop in reversed(hops):
        if hop not in trusted:
            return hop
    # Every hop is a trusted proxy: the request never crossed a boundary this
    # deployment can name, so key it on the outermost trusted address rather
    # than on client-supplied text.
    return hops[0]


def _constant_time_equals(presented: str, expected: str) -> bool:
    # Header values reach us latin-1 decoded, so a single non-ASCII byte in
    # X-Admin-Key makes secrets.compare_digest raise TypeError and turns a
    # failed authentication into a 500. Compare the encoded forms: the same
    # constant-time guarantee, and junk is merely wrong instead of fatal.
    return secrets.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def _trusted_proxies() -> frozenset[str]:
    raw = os.getenv("AGENTFLOW_TRUSTED_PROXIES", "").strip()
    if not raw:
        return frozenset()
    return frozenset(item.strip() for item in raw.split(",") if item.strip())
