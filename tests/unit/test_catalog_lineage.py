"""Event->metric lineage: the catalog must declare which events move each metric.

The mapping is pinned against the actual write path in
src/processing/local_pipeline._process_event:
  - order.*                    -> orders_v2 (and users_enriched)
  - click/page_view/add_to_cart -> sessions_aggregated
  - every event                -> pipeline_events (validated or deadletter)
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ingestion.schemas.events import EventType
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.semantic_layer.catalog import DataCatalog

ORDER_EVENTS = {"order.created", "order.updated", "order.cancelled"}
SESSION_EVENTS = {"click", "page_view", "add_to_cart"}
ALL_EVENT_TYPES = {event_type.value for event_type in EventType}


def test_every_metric_declares_lineage():
    catalog = DataCatalog()

    assert set(catalog.metrics) == {
        "revenue",
        "order_count",
        "avg_order_value",
        "conversion_rate",
        "active_sessions",
        "error_rate",
    }
    for name, metric in catalog.metrics.items():
        assert metric.source_events, f"metric {name} declares no source events"
        assert metric.source_table, f"metric {name} declares no source table"


def test_lineage_event_types_exist_in_the_ingestion_schema():
    catalog = DataCatalog()

    for name, metric in catalog.metrics.items():
        unknown = set(metric.source_events) - ALL_EVENT_TYPES
        assert not unknown, f"metric {name} references unknown event types: {unknown}"


def test_order_metrics_follow_the_orders_write_path():
    catalog = DataCatalog()

    for name in ("revenue", "order_count", "avg_order_value"):
        metric = catalog.metrics[name]
        assert set(metric.source_events) == ORDER_EVENTS
        assert metric.source_table == "orders_v2"
        assert metric.source_table in metric.sql_template


def test_session_metrics_follow_the_clickstream_write_path():
    catalog = DataCatalog()

    for name in ("conversion_rate", "active_sessions"):
        metric = catalog.metrics[name]
        assert set(metric.source_events) == SESSION_EVENTS
        assert metric.source_table == "sessions_aggregated"
        assert metric.source_table in metric.sql_template


def test_error_rate_is_moved_by_every_event_type():
    catalog = DataCatalog()

    metric = catalog.metrics["error_rate"]
    assert set(metric.source_events) == ALL_EVENT_TYPES
    assert metric.source_table == "pipeline_events"


def test_serialize_metrics_exposes_lineage_fields():
    serialized = DataCatalog().serialize_metrics()

    for name, payload in serialized.items():
        assert payload["source_events"], name
        assert payload["source_table"], name


def test_catalog_endpoint_returns_lineage():
    # The production /v1/catalog handler lives in main.py (importing main
    # strips the shadowed GET /catalog route from the shared agent router),
    # so pin the lineage payload on that handler, not on the agent-router copy.
    from src.serving.api.main import catalog as production_catalog

    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.get("/v1/catalog")(production_catalog)
    client = TestClient(app)

    response = client.get("/v1/catalog")

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert set(metrics["revenue"]["source_events"]) == ORDER_EVENTS
    assert metrics["revenue"]["source_table"] == "orders_v2"
    assert set(metrics["error_rate"]["source_events"]) == ALL_EVENT_TYPES


def test_agent_router_catalog_copy_stays_consistent():
    """agent_query.get_catalog survives only off-main builds; keep its payload
    shape consistent with the production serializer all the same."""
    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.include_router(agent_router, prefix="/v1")
    client = TestClient(app)

    response = client.get("/v1/catalog")
    if response.status_code == 404:
        # main.py was imported earlier in this process and stripped the
        # shadowed route from the shared router — nothing left to compare.
        return

    metrics = response.json()["metrics"]
    assert set(metrics["revenue"]["source_events"]) == ORDER_EVENTS
    assert metrics["revenue"]["source_table"] == "orders_v2"
