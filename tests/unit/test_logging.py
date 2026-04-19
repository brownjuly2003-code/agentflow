import json

import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import logger as logger_module
from src.serving.api.middleware.logging import build_correlation_middleware


def test_add_otel_context_adds_trace_and_span_ids(monkeypatch):
    class RecordingSpan:
        def is_recording(self) -> bool:
            return True

        def get_span_context(self):
            class SpanContext:
                trace_id = int("4bf92f3577b34da6a3ce929d0e0e4736", 16)
                span_id = int("00f067aa0ba902b7", 16)

            return SpanContext()

    monkeypatch.setattr(
        logger_module.trace,
        "get_current_span",
        lambda: RecordingSpan(),
    )

    event_dict = logger_module.add_otel_context(None, "info", {"event": "test"})

    assert event_dict["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert event_dict["span_id"] == "00f067aa0ba902b7"


def test_add_otel_context_skips_ids_without_recording_span(monkeypatch):
    class NonRecordingSpan:
        def is_recording(self) -> bool:
            return False

    monkeypatch.setattr(
        logger_module.trace,
        "get_current_span",
        lambda: NonRecordingSpan(),
    )

    event_dict = logger_module.add_otel_context(None, "info", {"event": "test"})

    assert "trace_id" not in event_dict
    assert "span_id" not in event_dict


def test_configure_logging_renders_json_with_contextvars():
    factory = structlog.testing.CapturingLoggerFactory()

    structlog.reset_defaults()
    logger_module.configure_logging()
    structlog.configure(
        processors=structlog.get_config()["processors"],
        logger_factory=factory,
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        correlation_id="corr-123",
        tenant_id="acme",
        path="/v1/health",
    )

    structlog.get_logger().info("api_log")

    rendered = json.loads(factory.logger.calls[0].args[0])

    assert rendered["event"] == "api_log"
    assert rendered["correlation_id"] == "corr-123"
    assert rendered["tenant_id"] == "acme"
    assert rendered["path"] == "/v1/health"


def test_correlation_middleware_echoes_header_and_preserves_context(monkeypatch):
    class RecordingSpan:
        def is_recording(self) -> bool:
            return True

        def get_span_context(self):
            class SpanContext:
                trace_id = int("4bf92f3577b34da6a3ce929d0e0e4736", 16)
                span_id = int("00f067aa0ba902b7", 16)

            return SpanContext()

    factory = structlog.testing.CapturingLoggerFactory()
    monkeypatch.setattr(
        logger_module.trace,
        "get_current_span",
        lambda: RecordingSpan(),
    )

    structlog.reset_defaults()
    logger_module.configure_logging()
    structlog.configure(
        processors=structlog.get_config()["processors"],
        logger_factory=factory,
        cache_logger_on_first_use=False,
    )

    app = FastAPI()

    @app.middleware("http")
    async def bind_tenant(request, call_next):
        request.state.tenant_id = "acme"
        structlog.contextvars.bind_contextvars(tenant_id="acme")
        return await call_next(request)

    app.middleware("http")(build_correlation_middleware())

    @app.get("/v1/ping")
    async def ping():
        structlog.get_logger().info("request_complete")
        return {"context": structlog.contextvars.get_contextvars()}

    with TestClient(app) as client:
        response = client.get("/v1/ping", headers={"X-Correlation-ID": "corr-abc"})

    rendered = json.loads(factory.logger.calls[0].args[0])

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "corr-abc"
    assert response.json()["context"] == {
        "correlation_id": "corr-abc",
        "path": "/v1/ping",
        "tenant_id": "acme",
    }
    assert rendered["correlation_id"] == "corr-abc"
    assert rendered["tenant_id"] == "acme"
    assert rendered["path"] == "/v1/ping"
    assert rendered["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert rendered["span_id"] == "00f067aa0ba902b7"


def test_correlation_middleware_falls_back_to_request_id_header():
    app = FastAPI()
    app.middleware("http")(build_correlation_middleware())

    @app.get("/v1/ping")
    async def ping():
        return {"context": structlog.contextvars.get_contextvars()}

    with TestClient(app) as client:
        response = client.get("/v1/ping", headers={"X-Request-Id": "req-123"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "req-123"
    assert response.json()["context"]["correlation_id"] == "req-123"


def test_correlation_middleware_generates_id_when_missing():
    app = FastAPI()
    app.middleware("http")(build_correlation_middleware())

    @app.get("/v1/ping")
    async def ping():
        return {"context": structlog.contextvars.get_contextvars()}

    with TestClient(app) as client:
        response = client.get("/v1/ping")

    correlation_id = response.headers["X-Correlation-ID"]

    assert response.status_code == 200
    assert correlation_id
    assert response.json()["context"]["correlation_id"] == correlation_id
