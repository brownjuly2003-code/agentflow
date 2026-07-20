"""Production profile hides interactive docs and the OpenAPI schema (audit G-2).

``/docs``, ``/openapi*`` are auth-exempt (``_is_exempt_path``), so a
production deployment would hand any unauthenticated caller the full route
map. ``production_docs_guard`` 404s ``/docs``, ``/redoc`` and ``/openapi*``
on ``profile=production`` only — demo/dev keep the local DX, mirroring the
CORS-wildcard policy (P2-3).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager
from src.serving.api.main import app


@pytest.fixture(autouse=True)
def _auth_manager() -> Iterator[None]:
    # TestClient without the lifespan: provide the auth manager the
    # middleware chain expects (same idiom as the CORS tests).
    state = app.state._state
    sentinel = object()
    prev = state.get("auth_manager", sentinel)
    manager = AuthManager()
    manager.load()
    state["auth_manager"] = manager
    yield
    if prev is sentinel:
        state.pop("auth_manager", None)
    else:
        state["auth_manager"] = prev


@contextmanager
def _profile(value: str) -> Iterator[None]:
    # The guard reads app.state.profile per request (set by lifespan in real
    # boots); pin it directly and restore so no state leaks across tests.
    state = app.state._state
    sentinel = object()
    prev = state.get("profile", sentinel)
    state["profile"] = value
    try:
        yield
    finally:
        if prev is sentinel:
            state.pop("profile", None)
        else:
            state["profile"] = prev


def test_docs_and_schema_stay_visible_outside_production() -> None:
    client = TestClient(app)
    with _profile("dev"):
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_production_profile_hides_docs_and_schema() -> None:
    client = TestClient(app)
    with _profile("production"):
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404, path
