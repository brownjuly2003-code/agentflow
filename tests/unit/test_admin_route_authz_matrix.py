"""S12 — every admin surface depends on ``require_admin_key``.

Admin paths intentionally skip the X-API-Key middleware
(``_is_admin_path``) and rely on the FastAPI dependency instead. A route
registered under ``/v1/admin`` or ``/admin`` without that dependency would
be unauthenticated. This inventory pins the contract so a new admin endpoint
cannot land open.
"""

from __future__ import annotations

from src.serving.api.main import app


def _dependency_names(route) -> set[str]:
    names: set[str] = set()
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return names
    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", repr(call)))
        stack.extend(getattr(dep, "dependencies", []) or [])
    return names


def test_all_admin_routes_require_admin_key() -> None:
    admin_routes = [
        route
        for route in app.routes
        if (path := getattr(route, "path", None))
        and (path.startswith("/v1/admin") or path.startswith("/admin"))
    ]
    assert admin_routes, "expected at least one admin route on the app"

    missing = [
        f"{sorted(getattr(route, 'methods', None) or [])} {route.path}"
        for route in admin_routes
        if "require_admin_key" not in _dependency_names(route)
    ]
    assert missing == [], f"admin routes without require_admin_key: {missing}"


def test_node_events_is_auth_middleware_exempt_not_open() -> None:
    """``/v1/node/events`` skips X-API-Key but must not be unauthenticated —
    the endpoint owns its bearer check. Pin both halves of that contract."""
    from src.serving.api.auth.middleware import _is_exempt_path
    from src.serving.node import ingest as ingest_module

    assert _is_exempt_path("/v1/node/events")
    # The handler is the function that compares the bearer to AGENTFLOW_NODE_TOKEN.
    source = ingest_module.ingest_node_events.__code__.co_names
    assert "compare_digest" in source or "_extract_bearer" in (
        ingest_module.ingest_node_events.__code__.co_names
    )
    assert hasattr(ingest_module, "_extract_bearer")
