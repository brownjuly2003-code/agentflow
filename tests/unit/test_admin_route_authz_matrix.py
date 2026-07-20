"""S12 — every admin surface depends on ``require_admin_key``.

Admin paths intentionally skip the X-API-Key middleware
(``_is_admin_path``) and rely on the FastAPI dependency instead. A route
registered under ``/v1/admin`` or ``/admin`` without that dependency would
be unauthenticated. Pin the dependency on the router objects themselves —
more stable than walking ``app.routes`` (which can look different under
coverage / import order on CI).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi.params import Depends

from src.serving.api.auth.middleware import _is_admin_path, _is_exempt_path, require_admin_key
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


# ── G-4: walk the ASSEMBLED app, not just the two known router objects ──────
#
# The router pins above can't see a THIRD admin router registered without the
# dependency — that route would ship fully open (middleware skips admin paths
# by design). The walk below closes that gap; the probe test below it proves
# the checker is able to fail (a detector that can't fail proves nothing).


def _iter_leaf_routes(
    routes: list, prefix: str, inherited: tuple
) -> Iterator[tuple[str, object, tuple]]:
    """Yield ``(full_path, route, inherited_dependency_calls)`` leaves.

    FastAPI ≥0.139 no longer flattens ``include_router`` into ``app.routes``:
    the app holds lazy ``_IncludedRouter`` nodes (no ``path`` attribute) whose
    children live in ``.original_router.routes`` with the router's own prefix
    already applied; the include-time prefix/dependencies sit on
    ``.include_context``. Older FastAPI keeps flattened ``APIRoute`` lists —
    this walk handles both.
    """
    for route in routes:
        context = getattr(route, "include_context", None)
        original = getattr(route, "original_router", None)
        if context is not None and original is not None:
            include_deps = tuple(
                _dependency_calls(list(getattr(context, "dependencies", []) or []))
            )
            yield from _iter_leaf_routes(
                original.routes,
                prefix + (getattr(context, "prefix", "") or ""),
                inherited + include_deps,
            )
            continue
        yield prefix + getattr(route, "path", ""), route, inherited


def _admin_routes_missing_admin_key(app: object) -> list[str]:
    from fastapi.routing import APIRoute

    missing: list[str] = []
    for path, route, inherited in _iter_leaf_routes(app.routes, "", ()):  # type: ignore[attr-defined]
        if not _is_admin_path(path):
            continue
        if not isinstance(route, APIRoute):
            # A mount / raw Starlette route under an admin prefix has no
            # FastAPI dependency chain at all — flag it.
            missing.append(path)
            continue
        calls = _dependency_calls(list(route.dependant.dependencies)) | set(inherited)
        if require_admin_key not in calls:
            missing.append(path)
    return missing


def test_every_assembled_admin_route_requires_admin_key() -> None:
    from src.serving.api.main import app

    admin_paths = [
        path
        for path, _route, _inherited in _iter_leaf_routes(app.routes, "", ())
        if _is_admin_path(path)
    ]
    assert len(admin_paths) >= 2, "expected admin routes on the assembled app"
    assert _admin_routes_missing_admin_key(app) == []


def test_admin_key_checker_flags_an_unprotected_route() -> None:
    from fastapi import APIRouter, FastAPI
    from fastapi import Depends as FastDepends

    probe = FastAPI()
    open_router = APIRouter(prefix="/v1/admin")

    @open_router.get("/leak")
    def _leak() -> dict:  # pragma: no cover — never called
        return {}

    guarded_router = APIRouter(prefix="/admin", dependencies=[FastDepends(require_admin_key)])

    @guarded_router.get("/ok")
    def _ok() -> dict:  # pragma: no cover — never called
        return {}

    probe.include_router(open_router)
    probe.include_router(guarded_router)

    assert _admin_routes_missing_admin_key(probe) == ["/v1/admin/leak"]
