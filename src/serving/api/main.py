"""Agent Query API — the interface between AI agents and the data platform.

FastAPI application that serves real-time data to AI agents via:
- Entity lookups (order, user, product details)
- Metric queries (revenue, conversion, latency)
- Natural language → SQL queries
- Pipeline health checks (so agents know if data is fresh)
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from src.quality.monitors.metrics_collector import HealthCollector
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources on startup."""
    logger.info("api_starting")

    app.state.catalog = DataCatalog()
    app.state.query_engine = QueryEngine(catalog=app.state.catalog)
    app.state.health_collector = HealthCollector()

    logger.info("api_ready", entities=len(app.state.catalog.entities))
    yield
    logger.info("api_shutting_down")


app = FastAPI(
    title="AgentFlow Query API",
    description="Real-time data access for AI agents",
    version="1.0.0",
    lifespan=lifespan,
)

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
