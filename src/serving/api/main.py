"""Agent Query API — the interface between AI agents and the data platform.

FastAPI application that serves real-time data to AI agents via:
- Entity lookups (order, user, product details)
- Metric queries (revenue, conversion, latency)
- Natural language → SQL queries
- Pipeline health checks (so agents know if data is fresh)

Security: API key authentication + per-key rate limiting.
"""

import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from src.quality.monitors.metrics_collector import HealthCollector
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine

logger = structlog.get_logger()

# API keys loaded from env. Format: comma-separated "key:name" pairs.
# Example: AGENTFLOW_API_KEYS="sk-abc123:support-agent,sk-def456:ops-agent"
_API_KEY_ENV = os.getenv("AGENTFLOW_API_KEYS", "")

# Rate limit: requests per minute per API key
_RATE_LIMIT_RPM = int(os.getenv("AGENTFLOW_RATE_LIMIT_RPM", "120"))


def _parse_api_keys(raw: str) -> dict[str, str]:
    """Parse 'key:name,key:name' into {key: name}."""
    if not raw.strip():
        return {}
    keys = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            key, name = pair.split(":", 1)
            keys[key.strip()] = name.strip()
        elif pair:
            keys[pair] = "unnamed"
    return keys


API_KEYS = _parse_api_keys(_API_KEY_ENV)

# Sliding window rate limiter: {api_key: [timestamp, ...]}
_rate_windows: dict[str, list[float]] = defaultdict(list)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources on startup."""
    logger.info("api_starting")

    app.state.catalog = DataCatalog()
    app.state.query_engine = QueryEngine(catalog=app.state.catalog)
    app.state.health_collector = HealthCollector()

    auth_mode = "api_key" if API_KEYS else "open (set AGENTFLOW_API_KEYS to enable)"
    logger.info(
        "api_ready",
        entities=len(app.state.catalog.entities),
        auth=auth_mode,
        rate_limit_rpm=_RATE_LIMIT_RPM,
    )
    yield
    logger.info("api_shutting_down")


app = FastAPI(
    title="AgentFlow Query API",
    description="Real-time data access for AI agents",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
    """API key authentication and per-key rate limiting middleware.

    - If AGENTFLOW_API_KEYS is set, requires X-API-Key header.
    - Rate limits each key to AGENTFLOW_RATE_LIMIT_RPM requests/minute.
    - Health and docs endpoints are exempt from auth.
    """
    path = request.url.path

    # Exempt paths: health, docs, metrics, openapi
    if path in ("/v1/health", "/docs", "/redoc", "/openapi.json") or path.startswith("/metrics"):
        return await call_next(request)

    # Auth check (skip if no keys configured — open mode for local dev)
    if API_KEYS:
        api_key = request.headers.get("X-API-Key", "")
        if api_key not in API_KEYS:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key. Pass X-API-Key header."},
            )

        # Rate limiting (sliding window)
        now = time.monotonic()
        window = _rate_windows[api_key]
        cutoff = now - 60.0
        _rate_windows[api_key] = [t for t in window if t > cutoff]

        if len(_rate_windows[api_key]) >= _RATE_LIMIT_RPM:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded: {_RATE_LIMIT_RPM} requests/minute",
                },
                headers={"Retry-After": "60"},
            )

        _rate_windows[api_key].append(now)

    return await call_next(request)


# Mount Prometheus metrics at /metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Agent query routes
app.include_router(agent_router, prefix="/v1")


@app.get("/v1/health")
async def health():
    """Pipeline health check — agents should call this before answering time-sensitive queries.

    Returns overall pipeline status and per-component health.
    If status != "healthy", agents should caveat their answers with data freshness warnings.
    """
    health_data = app.state.health_collector.collect()
    return health_data.to_dict()
