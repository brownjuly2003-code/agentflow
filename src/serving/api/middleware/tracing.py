from __future__ import annotations

from typing import Any

from fastapi import Request
from opentelemetry import trace
from opentelemetry.trace import Span

from src.processing.tracing import telemetry_disabled

HTTP_REQUEST_SPAN_NAME = "http.request"


def configure_server_request_span(span: Span, scope: dict[str, Any]) -> None:
    if telemetry_disabled() or not span.is_recording():
        return

    if hasattr(span, "update_name"):
        span.update_name(HTTP_REQUEST_SPAN_NAME)
    method = scope.get("method")
    if method is not None and hasattr(span, "set_attribute"):
        span.set_attribute("method", str(method))
    route = scope.get("path")
    if route is not None and hasattr(span, "set_attribute"):
        span.set_attribute("route", str(route))


def annotate_current_request_span(
    request: Request,
    status_code: int | None = None,
) -> None:
    if telemetry_disabled():
        return

    span = trace.get_current_span()
    if not span.is_recording():
        return

    if hasattr(span, "update_name"):
        span.update_name(HTTP_REQUEST_SPAN_NAME)
    if not hasattr(span, "set_attribute"):
        return

    span.set_attribute("method", request.method)
    route = getattr(request.scope.get("route"), "path", None) or request.url.path
    span.set_attribute("route", route)
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is not None:
        span.set_attribute("tenant_id", str(tenant_id))
    if status_code is not None:
        span.set_attribute("status_code", int(status_code))
