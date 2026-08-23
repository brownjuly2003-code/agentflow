from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request
from opentelemetry import trace
from opentelemetry.trace import Span

from agentflow_runtime.processing.tracing import telemetry_disabled
from agentflow_runtime.serving.api.middleware.redaction import redact_sensitive_path

HTTP_REQUEST_SPAN_NAME = "http.request"

# Raw-path attributes copied by OTel ASGI instrumentation before this hook.
# http.route is the matched template and is already safe — do not rewrite it.
_RAW_PATH_SPAN_ATTRIBUTES = ("http.target", "http.url", "url.path", "url.full")


def _redact_path_bearing_span_attributes(span: Span) -> None:
    existing = getattr(span, "attributes", None)
    if not isinstance(existing, Mapping):
        return
    for key in _RAW_PATH_SPAN_ATTRIBUTES:
        value = existing.get(key)
        if not isinstance(value, str):
            continue
        rewritten = redact_sensitive_path(value)
        if rewritten != value:
            span.set_attribute(key, rewritten)


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
        span.set_attribute("route", redact_sensitive_path(str(route)))
        _redact_path_bearing_span_attributes(span)


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
    route = getattr(request.scope.get("route"), "path", None) or redact_sensitive_path(
        request.url.path
    )
    span.set_attribute("route", route)
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is not None:
        span.set_attribute("tenant_id", str(tenant_id))
    if status_code is not None:
        span.set_attribute("status_code", int(status_code))
