from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

import src.serving.api.telemetry as telemetry_module
from src.serving.api.middleware.logging import build_correlation_middleware
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.api.telemetry import setup_telemetry
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine


class EngineStub:
    def execute_nl_query(self, question: str, context: dict | None = None) -> dict:
        return {
            "data": [{"answer": "ok"}, {"answer": "still-ok"}],
            "sql": "SELECT 1",
            "row_count": 2,
            "execution_time_ms": 5,
            "freshness_seconds": None,
        }


def test_setup_telemetry_does_not_crash():
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    setup_telemetry(app, span_exporter=InMemorySpanExporter())

    with TestClient(app) as client:
        response = client.get("/ping")

    assert response.status_code == 200


def test_fastapi_request_creates_trace_span():
    app = FastAPI()
    exporter = InMemorySpanExporter()

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    setup_telemetry(app, span_exporter=exporter)

    with TestClient(app) as client:
        response = client.get("/ping")

    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert any(span.attributes.get("http.route") == "/ping" for span in spans)


def test_nl_query_span_sets_attributes():
    app = FastAPI()
    exporter = InMemorySpanExporter()
    app.state.query_engine = EngineStub()
    app.include_router(agent_router, prefix="/v1")

    setup_telemetry(app, span_exporter=exporter)

    with TestClient(app) as client:
        response = client.post(
            "/v1/query",
            json={"question": "Top 5 products by revenue today"},
        )

    assert response.status_code == 200
    span = next(
        item
        for item in exporter.get_finished_spans()
        if item.name == "query_engine.translate"
    )
    assert span.attributes["query.text"] == "Top 5 products by revenue today"
    assert span.attributes["query.engine"] == "rule_based"
    assert span.attributes["query.sql"] == "SELECT 1"
    assert span.attributes["query.rows"] == 2


def test_query_request_creates_http_translate_and_duckdb_spans():
    app = FastAPI()
    exporter = InMemorySpanExporter()
    app.state.catalog = DataCatalog()
    app.state.query_engine = QueryEngine(catalog=app.state.catalog, db_path=":memory:")

    @app.middleware("http")
    async def bind_tenant(request, call_next):
        request.state.tenant_id = "acme"
        return await call_next(request)

    app.middleware("http")(build_correlation_middleware())
    app.include_router(agent_router, prefix="/v1")
    setup_telemetry(app, span_exporter=exporter)

    with TestClient(app) as client:
        response = client.post(
            "/v1/query",
            json={"question": "Top 5 products by revenue today"},
        )

    assert response.status_code == 200

    spans = {
        span.name: span
        for span in exporter.get_finished_spans()
        if span.name in {"http.request", "query_engine.translate", "duckdb.query"}
    }

    assert set(spans) == {"http.request", "query_engine.translate", "duckdb.query"}
    assert spans["query_engine.translate"].parent is not None
    assert spans["duckdb.query"].parent is not None
    assert (
        spans["query_engine.translate"].parent.span_id
        == spans["http.request"].context.span_id
    )
    assert (
        spans["duckdb.query"].parent.span_id
        == spans["query_engine.translate"].context.span_id
    )
    assert spans["http.request"].attributes["tenant_id"] == "acme"
    assert spans["query_engine.translate"].attributes["tenant_id"] == "acme"
    assert spans["duckdb.query"].attributes["tenant_id"] == "acme"


def test_setup_telemetry_respects_otel_sdk_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    app = FastAPI()
    exporter = InMemorySpanExporter()

    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    setup_telemetry(app, span_exporter=exporter)

    with TestClient(app) as client:
        response = client.get("/ping")

    assert response.status_code == 200
    assert list(exporter.get_finished_spans()) == []


def test_setup_telemetry_does_not_default_to_console_exporter(monkeypatch):
    app = FastAPI()
    console_calls: list[str] = []

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setattr(telemetry_module, "_tracer_provider", None)
    monkeypatch.setattr(telemetry_module, "_httpx_instrumented", False)
    monkeypatch.setattr(telemetry_module, "_registered_exporters", set())

    class _ConsoleTrap:
        def __init__(self, *args, **kwargs) -> None:
            console_calls.append("used")

        def export(self, spans) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr(telemetry_module, "ConsoleSpanExporter", _ConsoleTrap, raising=False)

    setup_telemetry(app)

    assert console_calls == []
