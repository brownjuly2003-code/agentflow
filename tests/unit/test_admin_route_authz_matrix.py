"""S12 — every admin surface depends on ``require_admin_key``.

Admin paths intentionally skip the X-API-Key middleware
(``_is_admin_path``) and rely on the FastAPI dependency instead. A route
registered under ``/v1/admin`` or ``/admin`` without that dependency would
be unauthenticated. Pin the dependency on the router objects themselves —
more stable than walking ``app.routes`` (which can look different under
coverage / import order on CI).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.params import Depends

from src.serving.api.auth.middleware import _is_exempt_path, require_admin_key
from src.serving.api.routers.admin import router as admin_router
from src.serving.api.routers.admin_ui import router as admin_ui_router
from src.serving.node import ingest as ingest_module


def _dependency_calls(dependencies: list) -> set[Callable]:
    calls: set[Callable] = set()
    for dep in dependencies:
        # Router-level: list[Depends]; route-level: Dependants with .call
        if isinstance(dep, Depends):
            if dep.dependency is not None:
                calls.add(dep.dependency)
            continue
        call = getattr(dep, "call", None) or getattr(dep, "dependency", None)
        if call is not None:
            calls.add(call)
    return calls


def test_admin_api_router_requires_admin_key() -> None:
    assert require_admin_key in _dependency_calls(list(admin_router.dependencies))
    assert admin_router.routes, "admin API router must expose routes"


def test_admin_ui_router_requires_admin_key() -> None:
    assert require_admin_key in _dependency_calls(list(admin_ui_router.dependencies))
    assert admin_ui_router.routes, "admin UI router must expose routes"


def test_node_events_is_auth_middleware_exempt_not_open() -> None:
    """``/v1/node/events`` skips X-API-Key but must not be unauthenticated —
    the endpoint owns its bearer check. Pin both halves of that contract."""
    assert _is_exempt_path("/v1/node/events")
    assert hasattr(ingest_module, "_extract_bearer")
    # ingest_node_events body must call secrets.compare_digest on the bearer.
    import inspect

    source = inspect.getsource(ingest_module.ingest_node_events)
    assert "compare_digest" in source
    assert "_extract_bearer" in source
