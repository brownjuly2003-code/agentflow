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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import TYPE_CHECKING, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from src.logger import configure_logging
from src.processing.outbox import OutboxProcessor
from src.quality.monitors.metrics_collector import HealthCollector
from src.serving.api.alert_dispatcher import AlertDispatcher
from src.serving.api.analytics import build_analytics_middleware, ensure_analytics_table
from src.serving.api.auth import AuthManager, TenantKey, build_auth_middleware
from src.serving.api.middleware.logging import build_correlation_middleware
from src.serving.api.middleware.metrics import build_metrics_middleware
from src.serving.api.routers.admin import router as admin_router
from src.serving.api.routers.admin_ui import router as admin_ui_router
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.api.routers.alerts import router as alert_router
from src.serving.api.routers.batch import router as batch_router
from src.serving.api.routers.contracts import router as contracts_router
from src.serving.api.routers.deadletter import router as deadletter_router
from src.serving.api.routers.lineage import router as lineage_router
from src.serving.api.routers.ops import router as ops_router
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
from src.serving.cache_invalidation import (
    MetricCacheController,
    journal_scan_fetch,
    publish_metrics_invalidate,
)
from src.serving.control_plane import control_plane_store_kind, get_control_plane_store
from src.serving.db_pool import DuckDBPool
from src.serving.node import resolve_node_config
from src.serving.node.emitter import NodeEmitter
from src.serving.node.ingest import router as node_ingest_router
from src.serving.node.seed import seed_node_baseline
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


def _env_float(name: str, fallback: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _env_int(name: str, fallback: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return fallback


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize shared resources on startup."""
    logger.info("api_starting")
    setup_telemetry(app)
    app.state.demo_mode = os.getenv("AGENTFLOW_DEMO_MODE", "").lower() == "true"
    app.state.demo_seed_on_boot = os.getenv("AGENTFLOW_SEED_ON_BOOT", "").lower() == "true"
    # Three-node demo topology (ADR 0012): resolve role/branch/token once here
    # and fail fast on a misconfigured node. Unset role == standalone, which is
    # byte-identical to today's single-node demo (N1). The center ingest
    # endpoint and the edge emitter hang off this resolved config.
    app.state.node_config = resolve_node_config()
    app.state.node_role = app.state.node_config.role
    app.state.node_branch = app.state.node_config.branch
    # Reset the auth-disabled bypass flag on every lifespan startup. This is a
    # process-wide attribute and tests may toggle it; without an explicit
    # reset a later TestClient lifespan with no configured keys would silently
    # bypass fail-closed (review P2 on auth/middleware).
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
        # Seeding is an opt-in, and off by default. It used to run inside the
        # constructor on every boot — before this flag was ever read — so a
        # production store got demo orders for no better reason than being empty
        # (audit P0-2).
        seed_demo_data=app.state.demo_seed_on_boot,
    )
    if app.state.demo_seed_on_boot:
        # The one path on which the API writes to a store it does not own, and
        # it takes an explicit opt-in. Otherwise the external backend is
        # read-only from here: its schema comes from
        # `python -m src.serving.provision` (or the bridge writer), and readiness
        # fails loudly when that never happened instead of quietly creating it.
        app.state.query_engine.provision_external_demo_store()
    if app.state.demo_mode and app.state.demo_seed_on_boot:
        # Three-node topology (ADR 0012 §7): lay down the per-branch journal
        # baseline (center = all branches, edge = its own, standalone = none)
        # so a center-first visitor sees a coherent cross-branch picture.
        seed_node_baseline(app.state.query_engine._conn, app.state.node_config)
    app.state.search_index = SearchIndex(
        catalog=app.state.catalog,
        query_engine=app.state.query_engine,
    )
    # Search rebuild must not block API startup: catalogue/query backend
    # transient failures should leave the rest of the surface online with
    # degraded search rather than crash the lifespan (M-C1 /
    # audit-2026-05).
    try:
        app.state.search_index.rebuild()
    except Exception:
        logger.warning("search_index_initial_rebuild_failed", exc_info=True)
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
    # Control-plane store (ADR 0010): resolve eagerly so a misconfigured
    # AGENTFLOW_CONTROLPLANE_STORE fails the boot, not the first delivery.
    # Reset any instance cached by a previous lifespan of this process-wide
    # app — the query engine above is fresh, the store must bind to it.
    app.state.control_plane_store = None
    control_plane_store = get_control_plane_store(app)
    # On the external (postgres) profile every control-plane consumer shares
    # the one store (slice 5); the embedded profile injects nothing, so the
    # consumers keep building their historical private stores (usage on its
    # own file, outbox on the engine's conn/path) exactly as before.
    shared_control_plane_store = (
        control_plane_store if control_plane_store_kind() != "embedded" else None
    )
    app.state.auth_manager = AuthManager(
        api_keys_path=os.getenv("AGENTFLOW_API_KEYS_FILE"),
        db_path=os.getenv("AGENTFLOW_USAGE_DB_PATH", "agentflow_api.duckdb"),
        admin_key=os.getenv("AGENTFLOW_ADMIN_KEY"),
        store=shared_control_plane_store,
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
    if shared_control_plane_store is None:
        # Embedded-profile bootstrap of the local api_sessions file table; the
        # postgres adapter creates its whole schema (sessions included) once
        # per process, so a stray local DuckDB file would be dead weight.
        ensure_analytics_table(app.state.auth_manager.db_path)
    app.state.webhook_dispatcher = WebhookDispatcher(app)
    # S7: metric-cache invalidation is a first-class controller (push from the
    # bridge + independent journal scan). It always starts — even when the
    # webhook dispatcher is held back for tests — so event-driven freshness is
    # not hostage to delivery-loop autostart. The historical monkey-patch over
    # dispatch_new_events is gone.
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    app.state.metric_cache_controller = MetricCacheController(
        app.state.query_cache,
        redis_url=redis_url,
        # newest_first window — an ascending limited scan reads the oldest
        # rows and goes blind once the journal outgrows it (issue #183).
        fetch_pipeline_events=journal_scan_fetch(app.state.query_engine),
    )
    app.state.metric_cache_controller.start()
    if getattr(app.state, "webhook_dispatcher_autostart", True):
        app.state.webhook_dispatcher.start()
    app.state.alert_dispatcher = AlertDispatcher(app)
    if getattr(app.state, "alert_dispatcher_autostart", True):
        app.state.alert_dispatcher.start()
    if shared_control_plane_store is not None:
        app.state.outbox_processor = OutboxProcessor(store=shared_control_plane_store)
    elif app.state.query_engine._db_path == ":memory:":
        app.state.outbox_processor = OutboxProcessor(conn=app.state.query_engine._conn)
    else:
        app.state.outbox_processor = OutboxProcessor(
            duckdb_path=app.state.query_engine._db_path,
        )
    app.state.outbox_processor_task = asyncio.create_task(app.state.outbox_processor.run_forever())

    # Edge role (ADR 0012): start the slow generator->forward emitter. Off in
    # center/standalone; tests disable it with AGENTFLOW_NODE_EMITTER_ENABLED=false.
    app.state.node_emitter = None
    app.state.node_emitter_task = None
    emitter_enabled = os.getenv("AGENTFLOW_NODE_EMITTER_ENABLED", "true").lower() != "false"
    if app.state.node_config.is_edge and emitter_enabled:
        app.state.node_emitter = NodeEmitter(
            config=app.state.node_config,
            conn=app.state.query_engine._conn,
            interval_seconds=_env_float("AGENTFLOW_NODE_EMIT_INTERVAL_SECONDS", 3.0),
            batch_size=_env_int("AGENTFLOW_NODE_EMIT_BATCH_SIZE", 5),
        )
        app.state.node_emitter.start()
        app.state.node_emitter_task = app.state.node_emitter.task

    # Serving bridge (S6), in-process arm. Only the DuckDB backend needs it:
    # `:memory:` (and a DuckDB file's single writer) cannot be reached from the
    # standalone bridge process, which is what the ClickHouse backend uses.
    # Off unless asked for — a demo without Kafka must not try to reach a broker.
    # Import is lazy so unit/coverage gates that never enable the bridge do not
    # pull confluent-kafka (and its native teardown) into every API import.
    app.state.serving_bridge = None
    app.state.serving_bridge_stop = None
    if _truthy(os.getenv("AGENTFLOW_SERVING_BRIDGE_ENABLED", "false")):
        if app.state.query_engine._backend_name != "duckdb":
            logger.warning("in_process_bridge_skipped_non_duckdb_backend")
        else:
            try:
                from src.processing.bridge_consumer import start_in_process_bridge

                loop = asyncio.get_running_loop()
                controller = app.state.metric_cache_controller

                def _on_batch_applied(event_ids: list[str]) -> None:
                    # Cross-process / multi-replica: every API pod listening on
                    # the channel drops metric keys. Same-process: schedule a
                    # local invalidate so we do not wait for the pub/sub round-trip.
                    publish_metrics_invalidate(redis_url, event_ids)
                    applied = list(event_ids)

                    def _schedule_local_invalidate() -> None:
                        asyncio.create_task(controller.notify_batch_applied(applied))

                    loop.call_soon_threadsafe(_schedule_local_invalidate)

                bridge, stop_event, _thread = start_in_process_bridge(
                    lake_conn=app.state.query_engine._conn,
                    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                    on_batch_applied=_on_batch_applied,
                )
                app.state.serving_bridge = bridge
                app.state.serving_bridge_stop = stop_event
            except Exception:
                # A missing broker degrades freshness, it does not take the API
                # down: every read path still serves.
                logger.warning("in_process_bridge_start_failed", exc_info=True)

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
    if getattr(app.state, "metric_cache_controller", None) is not None:
        await app.state.metric_cache_controller.stop()
    if getattr(app.state, "node_emitter", None) is not None:
        await app.state.node_emitter.stop()
    if getattr(app.state, "serving_bridge_stop", None) is not None:
        app.state.serving_bridge_stop.set()
    await app.state.query_cache.close()
    # Drain the queued api_usage rows before the process goes away; they are
    # written off the request path and would otherwise die with the queue.
    app.state.auth_manager.close_usage_writer()
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
async def demo_mode_guard(request: Request, call_next: RequestResponseEndpoint) -> Response:
    if getattr(request.app.state, "demo_mode", False):
        path = request.url.path
        if path.startswith("/v1/admin") or path.startswith("/admin"):
            return JSONResponse(status_code=404, content={"detail": "Not found."})
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path not in {
            "/v1/query",
            "/v1/query/explain",
            # Node federation ingest (ADR 0012): allow-listed past the demo
            # read-only guard so the token-authenticated edge->center POST is
            # not blocked; the endpoint's own bearer check still rejects the
            # public demo-key caller (N3).
            "/v1/node/events",
        }:
            return JSONResponse(
                status_code=403,
                content={"detail": "Demo mode is read-only for mutating routes."},
            )
    return await call_next(request)


# Registered last so it wraps every other HTTP middleware and observes the
# final response status code; route template is populated by the router after
# call_next() returns. Backs agentflow-api-health.json + api-5xx-spike.md.
app.middleware("http")(build_metrics_middleware())


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

# Agent query routes. /v1/catalog is NOT among them: the single catalog
# handler is main's richer one below (BACKLOG #26 removed the agent-router
# duplicate and the import-time route stripping that hid it).
app.include_router(agent_router, prefix="/v1")
app.include_router(batch_router, prefix="/v1")
app.include_router(admin_router, prefix="/v1")
app.include_router(admin_ui_router)
app.include_router(alert_router)
app.include_router(contracts_router, prefix="/v1")
app.include_router(deadletter_router)
app.include_router(lineage_router)
app.include_router(ops_router)
app.include_router(search_router, prefix="/v1")
app.include_router(slo_router)
app.include_router(stream_router)
app.include_router(webhook_router)
# Three-node topology (ADR 0012): the node-ingest router is mounted on every
# node but is a no-op (404) off the center and hidden from the public OpenAPI
# (include_in_schema=False). It carries its own bearer-token auth.
app.include_router(node_ingest_router)


@app.get("/v1/changelog", response_model=None)
async def changelog(request: Request) -> dict:
    """Return the configured date-based API version history."""
    return cast(dict, request.app.state.version_registry.changelog())


@app.get("/v1/catalog", response_model=None)
async def catalog(request: Request) -> dict:
    """List available entities, metrics, and streaming sources for agents."""
    catalog = request.app.state.catalog
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


@app.get("/v1/health", response_model=None)
async def health(request: Request) -> dict:
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
    return cast(dict, health_payload)
