"""F-02 A observability: secrets in /v1/admin/keys/... must not reach logs or traces."""

from __future__ import annotations

import json
from typing import Any

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.responses import Response

from agentflow_runtime import logger as logger_module
from agentflow_runtime.serving.api.middleware.logging import build_correlation_middleware
from agentflow_runtime.serving.api.middleware.redaction import redact_sensitive_path
from agentflow_runtime.serving.api.middleware.tracing import (
    annotate_current_request_span,
    configure_server_request_span,
)
from agentflow_runtime.serving.api.telemetry import setup_telemetry

_LEAK_PROBE = "ak_live_should_never_appear_in_obs_z9q3"


class _RecordingSpan:
    def __init__(self, attributes: dict[str, Any] | None = None) -> None:
        self.attributes: dict[str, Any] = dict(attributes or {})
        self.name: str | None = None

    def is_recording(self) -> bool:
        return True

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def update_name(self, name: str) -> None:
        self.name = name


def _assert_secret_absent(payload: object, secret: str) -> None:
    if isinstance(payload, str):
        assert secret not in payload
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            _assert_secret_absent(key, secret)
            _assert_secret_absent(value, secret)
        return
    if isinstance(payload, (list, tuple, set)):
        for item in payload:
            _assert_secret_absent(item, secret)
        return
    if payload is None or isinstance(payload, (int, float, bool)):
        return
    assert secret not in str(payload)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/v1/admin/keys", "/v1/admin/keys"),
        ("/v1/admin/keys/ak_live_abc123", "/v1/admin/keys/<redacted>"),
        (
            "/v1/admin/keys/ak_live_abc123/rotate",
            "/v1/admin/keys/<redacted>/rotate",
        ),
        ("/v1/metrics/revenue", "/v1/metrics/revenue"),
        ("", ""),
        (
            "v1/admin/keys/ak_live_abc123",
            "v1/admin/keys/<redacted>",
        ),
        ("/v1/admin/keys/", "/v1/admin/keys/"),
        (
            "/v1/admin/keys/ak_live_abc123/",
            "/v1/admin/keys/<redacted>/",
        ),
        (
            "/v1/admin/keys/ключ-юникод",
            "/v1/admin/keys/<redacted>",
        ),
        ("admin/keys/ak_live_abc123", "admin/keys/<redacted>"),
        ("/", "/"),
        ("/v1/admin/keysfoo/secret", "/v1/admin/keysfoo/secret"),
    ],
)
def test_redact_sensitive_path_rule(path: str, expected: str) -> None:
    assert redact_sensitive_path(path) == expected


def test_logging_delete_admin_keys_secret_absent_from_structured_logs() -> None:
    factory = structlog.testing.CapturingLoggerFactory()
    structlog.reset_defaults()
    logger_module.configure_logging()
    structlog.configure(
        processors=structlog.get_config()["processors"],
        logger_factory=factory,
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.clear_contextvars()

    app = FastAPI()
    app.middleware("http")(build_correlation_middleware())

    @app.delete("/v1/admin/keys/{key_id}")
    async def revoke(key_id: str) -> Response:
        structlog.get_logger().info("admin_key_delete")
        return Response(status_code=404)

    with TestClient(app) as client:
        response = client.delete(f"/v1/admin/keys/{_LEAK_PROBE}")

    assert response.status_code == 404
    assert factory.logger.calls, "expected at least one structured log record"

    for call in factory.logger.calls:
        for arg in call.args:
            _assert_secret_absent(arg, _LEAK_PROBE)
            if isinstance(arg, str):
                rendered = json.loads(arg)
                _assert_secret_absent(rendered, _LEAK_PROBE)
                if rendered.get("event") == "admin_key_delete":
                    assert rendered["path"] == "/v1/admin/keys/<redacted>"
        _assert_secret_absent(call.kwargs, _LEAK_PROBE)


def test_tracing_delete_admin_keys_secret_absent_from_span_attributes() -> None:
    app = FastAPI()
    exporter = InMemorySpanExporter()
    app.middleware("http")(build_correlation_middleware())

    @app.delete("/v1/admin/keys/{key_id}")
    async def revoke(key_id: str) -> Response:
        return Response(status_code=404)

    setup_telemetry(app, span_exporter=exporter)

    with TestClient(app) as client:
        response = client.delete(f"/v1/admin/keys/{_LEAK_PROBE}")

    assert response.status_code == 404
    spans = list(exporter.get_finished_spans())
    assert spans, "expected at least one finished span"

    for span in spans:
        attributes = dict(span.attributes or {})
        _assert_secret_absent(attributes, _LEAK_PROBE)
        _assert_secret_absent(span.name, _LEAK_PROBE)

    server = next(span for span in spans if span.name == "http.request")
    assert server.attributes["route"] == "/v1/admin/keys/{key_id}"
    assert server.attributes["http.target"] == "/v1/admin/keys/<redacted>"
    assert server.attributes["http.url"] == "http://testserver/v1/admin/keys/<redacted>"
    assert server.attributes.get("http.route") == "/v1/admin/keys/{key_id}"


def test_tracing_annotate_prefers_route_template(monkeypatch: pytest.MonkeyPatch) -> None:
    span = _RecordingSpan()
    monkeypatch.setattr(
        "agentflow_runtime.serving.api.middleware.tracing.trace.get_current_span",
        lambda: span,
    )
    monkeypatch.setattr(
        "agentflow_runtime.serving.api.middleware.tracing.telemetry_disabled",
        lambda: False,
    )

    route = type("Route", (), {"path": "/v1/admin/keys/{key_id}"})()
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "DELETE",
            "scheme": "http",
            "path": f"/v1/admin/keys/{_LEAK_PROBE}",
            "raw_path": f"/v1/admin/keys/{_LEAK_PROBE}".encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
            "route": route,
        }
    )
    annotate_current_request_span(request)

    assert span.attributes["route"] == "/v1/admin/keys/{key_id}"
    _assert_secret_absent(span.attributes, _LEAK_PROBE)


def test_tracing_annotate_redacts_raw_path_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    span = _RecordingSpan()
    monkeypatch.setattr(
        "agentflow_runtime.serving.api.middleware.tracing.trace.get_current_span",
        lambda: span,
    )
    monkeypatch.setattr(
        "agentflow_runtime.serving.api.middleware.tracing.telemetry_disabled",
        lambda: False,
    )

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "DELETE",
            "scheme": "http",
            "path": f"/v1/admin/keys/{_LEAK_PROBE}",
            "raw_path": f"/v1/admin/keys/{_LEAK_PROBE}".encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
    )
    annotate_current_request_span(request)

    assert span.attributes["route"] == "/v1/admin/keys/<redacted>"
    _assert_secret_absent(span.attributes, _LEAK_PROBE)


def test_tracing_configure_server_request_span_redacts_raw_path() -> None:
    span = _RecordingSpan(
        {
            "http.target": f"/v1/admin/keys/{_LEAK_PROBE}",
            "http.url": f"http://testserver/v1/admin/keys/{_LEAK_PROBE}",
            "http.route": "/v1/admin/keys/{key_id}",
        }
    )
    configure_server_request_span(
        span,
        {"method": "DELETE", "path": f"/v1/admin/keys/{_LEAK_PROBE}"},
    )

    assert span.attributes["route"] == "/v1/admin/keys/<redacted>"
    assert span.attributes["http.target"] == "/v1/admin/keys/<redacted>"
    assert span.attributes["http.url"] == "http://testserver/v1/admin/keys/<redacted>"
    assert span.attributes["http.route"] == "/v1/admin/keys/{key_id}"
    _assert_secret_absent(span.attributes, _LEAK_PROBE)
    _assert_secret_absent(span.name, _LEAK_PROBE)
