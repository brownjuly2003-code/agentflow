from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

import structlog
from fastapi import Request
from starlette.responses import Response

from src.serving.api.middleware.tracing import annotate_current_request_span

CORRELATION_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-Id"


def build_correlation_middleware():
    async def correlation_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = (
            request.headers.get(CORRELATION_HEADER)
            or request.headers.get(REQUEST_ID_HEADER)
            or str(uuid4())
        )
        request.state.correlation_id = correlation_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            path=request.url.path,
        )
        annotate_current_request_span(request)
        try:
            response = await call_next(request)
            annotate_current_request_span(request, response.status_code)
            response.headers[CORRELATION_HEADER] = correlation_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()

    return correlation_middleware
