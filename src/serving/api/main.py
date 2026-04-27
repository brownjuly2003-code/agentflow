"""Agent Query API - the interface between AI agents and the data platform.

FastAPI application that serves real-time data to AI agents via:
- Entity lookups (order, user, product details)
- Metric queries (revenue, conversion, latency)
- Natural language -> SQL queries
- Pipeline health checks (so agents know if data is fresh)

Security: API key authentication + per-key rate limiting.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from starlette.concurrency import run_in_threadpool

from src.logger import configure_logging
from src.processing.outbox import OutboxProcessor
from src.quality.monitors.metrics_collector import HealthCollector
from src.serving.api.alert_dispatcher import AlertDispatcher
from src.serving.api.analytics import build_analytics_middleware, ensure_analytics_table
from src.serving.api.auth import AuthManager, TenantKey, build_auth_middleware
from src.serving.api.middleware.logging import build_correlation_middleware
from src.serving.api.routers.admin import router as admin_router
from src.serving.api.routers.admin_ui import router as admin_ui_router
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.api.routers.alerts import router as alert_router
from src.serving.api.routers.batch import router as batch_router
from src.serving.api.routers.contracts import router as contracts_router
from src.serving.api.routers.deadletter import router as deadletter_router
from src.serving.api.routers.lineage import router as lineage_router
from src.serving.api.routers.search import router as search_router
from src.serving.api.routers.slo import router as slo_router
from src.serving.api.routers.stream import router as stream_router
from src.serving.api.routers.webhooks import router as webhook_router
from src.serving.api.security import build_security_headers_middleware
from src.serving.api.versioning import (
    ApiVersionRegistry,
    ResponseTransformer,
    build_versioning_middleware,
)
from src.serving.api.webhook_dispatcher import WebhookDispatcher
from src.serving.cache import QueryCache
from src.serving.db_pool import DuckDBPool
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine
from src.serving.semantic_layer.search_index import SearchIndex

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export import SpanExporter

try:
    from src.serving.api.telemetry import setup_telemetry
except ModuleNotFoundError:

    def setup_telemetry(
        app: FastAPI,
        span_exporter: "SpanExporter | None" = None,
    ) -> None:
        return None


configure_logging()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources on startup."""
    logger.info("api_starting")
    setup_telemetry(app)
    app.state.demo_mode = os.getenv("AGENTFLOW_DEMO_MODE", "").lower() == "true"
    app.state.demo_seed_on_boot = os.getenv("AGENTFLOW_SEED_ON_BOOT", "").lower() == "true"
    # Reset the auth-disabled bypass flag on every lifespan startup. This is a
    # process-wide attribute and tests may toggle it; without an explicit
    # reset a later TestClient lifespan with no configured keys would silently
    # bypass fail-closed (Codex review P2 on auth/middleware).
    app.state.auth_disabled = False

    app.state.version_registry = ApiVersionRegistry()
    app.state.response_transformer = ResponseTransformer(app.state.version_registry)
    app.state.catalog = DataCatalog()
    default_duckdb_pool_size = min(max((os.cpu_count() or 1) * 2, 4), 16)
    raw_duckdb_pool_size = os.getenv("DUCKDB_POOL_SIZE")
    try:
        app.state.duckdb_pool_size = (
            int(raw_duckdb_pool_size)
            if raw_duckdb_pool_size is not None
            else default_duckdb_pool_size
        )
    except ValueError:
        app.state.duckdb_pool_size = default_duckdb_pool_size
        logger.warning(
            "invalid_duckdb_pool_size",
            value=raw_duckdb_pool_size,
            fallback=default_duckdb_pool_size,
        )
    app.state.db_pool = DuckDBPool(
        db_path=os.getenv("DUCKDB_PATH", ":memory:"),
        pool_size=app.state.duckdb_pool_size,
    )
    app.state.db_pool.initialize()
    app.state.query_engine = QueryEngine(
        catalog=app.state.catalog,
        db_path=os.getenv("DUCKDB_PATH", ":memory:"),
        db_pool=app.state.db_pool,
    )
    if app.state.demo_mode and app.state.demo_seed_on_boot:
        app.state.query_engine._duckdb_backend.initialize_demo_data()
        if app.state.query_engine._backend_name != app.state.query_engine._duckdb_backend.name:
            app.state.query_engine._backend.initialize_demo_data()
    app.state.search_index = SearchIndex(
        catalog=app.state.catalog,
        query_engine=app.state.query_engine,
    )
    app.state.search_index.rebuild()
    app.state.search_index_rebuild_task = asyncio.create_task(
        app.state.search_index.rebuild_periodically(interval_seconds=60)
    )
    app.state.health_collector = HealthCollector()
    try:
        app.state.health_cache_ttl_seconds = float(
            os.getenv("AGENTFLOW_HEALTH_CACHE_TTL_SECONDS", "5")
        )
    except ValueError:
        app.state.health_cache_ttl_seconds = 5.0
        logger.warning(
            "invalid_health_cache_ttl_seconds",
            value=os.getenv("AGENTFLOW_HEALTH_CACHE_TTL_SECONDS"),
            fallback=5.0,
        )
    app.state.health_cache_payload = None
    app.state.health_cache_expires_at = 0.0
    app.state.health_cache_refresh_lock = asyncio.Lock()
    app.state.query_cache = QueryCache(redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"))
    try:
        app.state.cache_ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "30"))
    except ValueError:
        app.state.cache_ttl_seconds = 30
        logger.warning(
            "invalid_cache_ttl_seconds",
            value=os.getenv("CACHE_TTL_SECONDS"),
            fallback=30,
        )
    app.state.auth_manager = AuthManager(
        api_keys_path=os.getenv("AGENTFLOW_API_KEYS_FILE"),
        db_path=os.getenv("AGENTFLOW_USAGE_DB_PATH", "agentflow_api.duckdb"),
        admin_key=os.getenv("AGENTFLOW_ADMIN_KEY"),
    )
    app.state.auth_manager.load()
    if app.state.demo_mode:
        demo_api_key = os.getenv("DEMO_API_KEY", "demo-key")
        if demo_api_key not in app.state.auth_manager.keys_by_value:
            demo_key = TenantKey(
                key_id="demo-public",
                key=demo_api_key,
                name="Public Demo",
                tenant="default",
                rate_limit_rpm=60,
                allowed_entity_types=None,
                created_at=date.today(),
            )
            app.state.auth_manager.keys_by_value[demo_api_key] = demo_key
            if "demo-public" not in app.state.auth_manager._keys_by_id:
                app.state.auth_manager._keys_by_id["demo-public"] = demo_key
            if not any(
                item.key_id == "demo-public" for item in app.state.auth_manager._loaded_keys
            ):
                app.state.auth_manager._loaded_keys.append(demo_key)
            logger.info(
                "demo_mode_enabled",
                api_key_name=demo_key.name,
                rate_limit_rpm=demo_key.rate_limit_rpm,
                seed_on_boot=app.state.demo_seed_on_boot,
            )
    app.state.auth_manager.register_signal_handlers()
    app.state.auth_manager.ensure_usage_table()
    ensure_analytics_table(app.state.auth_manager.db_path)
    app.state.webhook_dispatcher = WebhookDispatcher(app)
    original_dispatch_new_events = app.state.webhook_dispatcher.dispatch_new_events

    async def dispatch_new_events_with_cache_invalidation():
        seen_before = len(app.state.webhook_dispatcher.seen_event_ids)
        await original_dispatch_new_events()
        if len(app.state.webhook_dispatcher.seen_event_ids) > seen_before:
            await app.state.query_cache.invalidate_metrics()

    app.state.webhook_dispatcher.dispatch_new_events = dispatch_new_events_with_cache_invalidation
    if getattr(app.state, "webhook_dispatcher_autostart", True):
        app.state.webhook_dispatcher.start()
    app.state.alert_dispatcher = AlertDispatcher(app)
    if getattr(app.state, "alert_dispatcher_autostart", True):
        app.state.alert_dispatcher.start()
    if app.state.query_engine._db_path == ":memory:":
        app.state.outbox_processor = OutboxProcessor(conn=app.state.query_engine._conn)
    else:
        app.state.outbox_processor = OutboxProcessor(
            duckdb_path=app.state.query_engine._db_path,
        )
    app.state.outbox_processor_task = asyncio.create_task(app.state.outbox_processor.run_forever())

    auth_mode = (
        "multi_tenant_api_keys"
        if app.state.auth_manager.has_configured_keys()
        else "open (set config/api_keys.yaml to enable)"
    )
    logger.info(
        "api_ready",
        entities=len(app.state.catalog.entities),
        auth=auth_mode,
        configured_keys=app.state.auth_manager.configured_key_count,
    )
    yield
    app.state.search_index_rebuild_task.cancel()
    try:
        await app.state.search_index_rebuild_task
    except asyncio.CancelledError:
        pass
    app.state.outbox_processor_task.cancel()
    try:
        await app.state.outbox_processor_task
    except asyncio.CancelledError:
        pass
    await app.state.alert_dispatcher.stop()
    await app.state.webhook_dispatcher.stop()
    await app.state.query_cache.close()
    app.state.db_pool.close()
    logger.info("api_shutting_down")


app = FastAPI(
    title="AgentFlow Query API",
    description="Real-time data access for AI agents",
    version="1.0.0",
    lifespan=lifespan,
)
app.middleware("http")(build_auth_middleware())
app.middleware("http")(build_versioning_middleware())
app.middleware("http")(build_analytics_middleware())
app.middleware("http")(build_security_headers_middleware())
app.middleware("http")(build_correlation_middleware())


@app.middleware("http")
async def demo_mode_guard(request: Request, call_next):
    if getattr(request.app.state, "demo_mode", False):
        path = request.url.path
        if path.startswith("/v1/admin") or path.startswith("/admin"):
            return JSONResponse(status_code=404, content={"detail": "Not found."})
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path not in {
            "/v1/query",
            "/v1/query/explain",
        }:
            return JSONResponse(
                status_code=403,
                content={"detail": "Demo mode is read-only for mutating routes."},
            )
    return await call_next(request)


cors_origins = [
    origin.strip()
    for origin in os.getenv("AGENTFLOW_CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type", "Authorization"],
    expose_headers=["X-Cache", "X-Request-Id", "X-Process-Time"],
)

# Mount Prometheus metrics at /metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Agent query routes
agent_router.routes[:] = [
    route
    for route in agent_router.routes
    if not (
        getattr(route, "path", None) == "/catalog" and "GET" in getattr(route, "methods", set())
    )
]
app.include_router(agent_router, prefix="/v1")
app.include_router(batch_router, prefix="/v1")
app.include_router(admin_router, prefix="/v1")
app.include_router(admin_ui_router)
app.include_router(alert_router)
app.include_router(contracts_router, prefix="/v1")
app.include_router(deadletter_router)
app.include_router(lineage_router)
app.include_router(search_router, prefix="/v1")
app.include_router(slo_router)
app.include_router(stream_router)
app.include_router(webhook_router)


@app.get("/v1/changelog")
async def changelog():
    """Return the configured date-based API version history."""
    return app.state.version_registry.changelog()


@app.get("/v1/catalog")
async def catalog():
    """List available entities, metrics, and streaming sources for agents."""
    catalog = app.state.catalog
    return {
        "entities": catalog.serialize_entities(),
        "metrics": catalog.serialize_metrics(),
        "streaming_sources": {
            "events": {
                "path": "/v1/stream/events",
                "transport": "sse",
                "description": "Real-time stream of validated pipeline events",
                "filters": {
                    "event_type": ["order", "payment", "clickstream", "inventory"],
                    "entity_id": "Filter to a specific entity identifier",
                },
            }
        },
        "audit_sources": {
            "lineage": {
                "path": "/v1/lineage/{entity_type}/{entity_id}",
                "description": "Provenance chain from source through serving for a specific entity",
                "layers": [
                    "source",
                    "ingestion",
                    "validation",
                    "enrichment",
                    "serving",
                ],
            }
        },
    }


@app.get("/v1/health")
async def health(request: Request):
    """Pipeline health check - agents should call this before answering time-sensitive queries.

    Returns overall pipeline status and per-component health.
    If status != "healthy", agents should caveat their answers with data freshness warnings.
    """
    now = asyncio.get_running_loop().time()
    health_payload = (
        request.app.state.health_cache_payload
        if now < request.app.state.health_cache_expires_at
        else None
    )
    if health_payload is None:
        async with request.app.state.health_cache_refresh_lock:
            now = asyncio.get_running_loop().time()
            health_payload = (
                request.app.state.health_cache_payload
                if now < request.app.state.health_cache_expires_at
                else None
            )
            if health_payload is None:
                health_data = await run_in_threadpool(request.app.state.health_collector.collect)
                health_payload = health_data.to_dict()
                pool_stats = request.app.state.db_pool.stats()
                health_payload["components"].append(
                    {
                        "name": "duckdb_pool",
                        "status": "healthy",
                        "message": (
                            f"{pool_stats['read_in_use']}/{pool_stats['pool_size']} "
                            "read connections in use"
                        ),
                        "metrics": pool_stats,
                        "source": "live",
                    }
                )
                request.app.state.health_cache_payload = health_payload
                request.app.state.health_cache_expires_at = (
                    now + request.app.state.health_cache_ttl_seconds
                )
    return health_payload
