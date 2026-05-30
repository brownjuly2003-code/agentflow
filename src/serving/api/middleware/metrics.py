from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import Response

from src.serving.api.metrics import HTTP_REQUESTS

UNMATCHED_ROUTE_LABEL = "<unmatched>"


def _route_label(request: Request) -> str:
    # request.scope["route"] is populated by the router AFTER all user
    # middlewares finish. Responses produced by an earlier middleware that
    # short-circuits before call_next reaches the router (auth 401/429/503,
    # demo_mode_guard) will fall into UNMATCHED_ROUTE_LABEL — route-level
    # breakdowns for those live on dedicated counters such as
    # agentflow_auth_failures_total.
    route = request.scope.get("route")
    path_template = getattr(route, "path", None)
    return path_template or UNMATCHED_ROUTE_LABEL


def build_metrics_middleware() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    async def metrics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            response = await call_next(request)
        except Exception:
            HTTP_REQUESTS.labels(
                method=request.method,
                route=_route_label(request),
                status="500",
            ).inc()
            raise
        HTTP_REQUESTS.labels(
            method=request.method,
            route=_route_label(request),
            status=str(response.status_code),
        ).inc()
        return response

    return metrics_middleware
