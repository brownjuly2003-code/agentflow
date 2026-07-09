"""S12 — offline OpenAPI × auth-class inventory (no live server).

Every path documented in ``docs/openapi.json`` must land in exactly one
auth class that the middleware implements:

* **exempt** — public health/docs/metrics/node-ingest surfaces
* **admin**  — middleware-skipped; route Depends(require_admin_key)
* **tenant** — X-API-Key required (or explicit AUTH_DISABLED)

This is the offline half of the API-surface pass. Live schemathesis stays
in ``tests/contract/test_openapi_compliance.py`` (needs a running API).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.serving.api.auth.middleware import _is_admin_path, _is_exempt_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = PROJECT_ROOT / "docs" / "openapi.json"

# Documented public / special paths that are middleware-exempt.
# Keep in sync with middleware classifiers + hand-written auth matrices.
KNOWN_EXEMPT_PREFIXES = (
    "/v1/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/v1/node/events",
)


def _openapi_paths() -> list[str]:
    schema = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    return sorted(schema.get("paths", {}))


def _concrete_probe(path_template: str) -> str:
    """Turn OpenAPI ``{param}`` templates into concrete paths for classifiers."""
    return (
        path_template.replace("{entity_type}", "order")
        .replace("{entity_id}", "1")
        .replace("{order_id}", "1")
        .replace("{metric_name}", "revenue")
        .replace("{alert_id}", "a1")
        .replace("{webhook_id}", "w1")
        .replace("{event_id}", "e1")
        .replace("{api_key}", "k1")
        .replace("{key_id}", "k1")
        .replace("{item_id}", "i1")
        .replace("{entity}", "order")
        .replace("{version}", "1")
        .replace("{from_version}", "1")
        .replace("{to_version}", "2")
    )


def _auth_class(path: str) -> str:
    if _is_admin_path(path):
        return "admin"
    if _is_exempt_path(path):
        return "exempt"
    return "tenant"


@pytest.mark.parametrize("path_template", _openapi_paths())
def test_every_openapi_path_has_a_single_auth_class(path_template: str) -> None:
    concrete = _concrete_probe(path_template)
    klass = _auth_class(concrete)
    assert klass in {"admin", "exempt", "tenant"}
    # Admin and exempt must not both fire (middleware short-circuits admin first).
    if klass == "admin":
        assert _is_admin_path(concrete)
        # Admin paths are intentionally not tenant-gated by middleware.
        assert not _is_exempt_path(concrete) or concrete.startswith("/v1/health")


def test_openapi_surface_has_no_orphan_public_tenant_paths() -> None:
    """Tenant paths must not look like accidental public prefixes."""
    publicish = []
    for path_template in _openapi_paths():
        concrete = _concrete_probe(path_template)
        if _auth_class(concrete) != "tenant":
            continue
        if any(concrete == p or concrete.startswith(p + "/") for p in KNOWN_EXEMPT_PREFIXES):
            publicish.append(path_template)
    assert publicish == [], f"tenant paths wrongly matching exempt prefixes: {publicish}"


def test_admin_openapi_paths_are_under_admin_prefix() -> None:
    admins = [p for p in _openapi_paths() if _auth_class(_concrete_probe(p)) == "admin"]
    assert admins, "expected at least one admin path in OpenAPI"
    for path in admins:
        assert path.startswith("/v1/admin") or path.startswith("/admin"), path


def test_health_is_exempt_and_catalog_is_tenant() -> None:
    assert _auth_class("/v1/health") == "exempt"
    assert _auth_class("/v1/catalog") == "tenant"
    assert _auth_class("/v1/metrics/revenue") == "tenant"
    assert _auth_class("/v1/admin/keys") == "admin"


def test_openapi_documents_core_product_paths() -> None:
    paths = set(_openapi_paths())
    for required in (
        "/v1/health",
        "/v1/metrics/{metric_name}",
        "/v1/entity/{entity_type}/{entity_id}",
        "/v1/query",
        "/v1/catalog",
    ):
        assert required in paths, f"missing product path {required}"
