from pathlib import Path

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager, build_auth_middleware
from src.serving.api.routers.admin import router as admin_router


def _write_api_keys(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _build_app(
    api_keys_path: Path,
    db_path: Path,
    admin_key: str = "admin-secret",
) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        admin_key=admin_key,
    )
    app.state.auth_manager.load()
    app.state.auth_manager.ensure_usage_table()
    app.middleware("http")(build_auth_middleware())
    app.include_router(admin_router, prefix="/v1")

    @app.get("/v1/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/v1/entity/{entity_type}/{entity_id}")
    async def get_entity(entity_type: str, entity_id: str):
        return {"entity_type": entity_type, "entity_id": entity_id}

    @app.get("/v1/metrics/revenue")
    async def revenue():
        return {"metric_name": "revenue", "value": 100.0}

    return app


@pytest.fixture
def api_keys_path(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "api_keys.yaml"
    _write_api_keys(
        path,
        """
        keys:
          - key: "tenant-order-key"
            name: "Order Agent"
            tenant: "acme"
            rate_limit_rpm: 2
            allowed_entity_types: ["order"]
            created_at: "2026-04-10"
          - key: "tenant-ops-key"
            name: "Ops Agent"
            tenant: "acme"
            rate_limit_rpm: 3
            allowed_entity_types: null
            created_at: "2026-04-10"
        """,
    )
    return path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "usage.duckdb"


def test_load_reads_multi_tenant_keys(api_keys_path: Path, db_path: Path):
    manager = AuthManager(api_keys_path=api_keys_path, db_path=db_path, admin_key="admin-secret")

    manager.load()

    assert sorted(manager.keys_by_value) == ["tenant-ops-key", "tenant-order-key"]
    assert manager.keys_by_value["tenant-order-key"].allowed_entity_types == ["order"]
    assert manager.keys_by_value["tenant-ops-key"].tenant == "acme"


def test_reload_picks_up_file_changes(api_keys_path: Path, db_path: Path):
    manager = AuthManager(api_keys_path=api_keys_path, db_path=db_path, admin_key="admin-secret")
    manager.load()
    _write_api_keys(
        api_keys_path,
        """
        keys:
          - key: "replacement-key"
            name: "Replacement Agent"
            tenant: "beta"
            rate_limit_rpm: 5
            allowed_entity_types: null
            created_at: "2026-04-10"
        """,
    )

    manager.reload()

    assert list(manager.keys_by_value) == ["replacement-key"]


def test_missing_api_key_returns_401(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app(api_keys_path, db_path))

    response = client.get("/v1/metrics/revenue")

    assert response.status_code == 401


def test_invalid_api_key_returns_401(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app(api_keys_path, db_path))

    response = client.get("/v1/metrics/revenue", headers={"X-API-Key": "bad-key"})

    assert response.status_code == 401


def test_allowed_entity_types_block_forbidden_entities(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app(api_keys_path, db_path))

    response = client.get("/v1/entity/user/USR-1", headers={"X-API-Key": "tenant-order-key"})

    assert response.status_code == 403


def test_rate_limit_is_isolated_per_key(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app(api_keys_path, db_path))

    first = client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})
    second = client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})
    third = client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-order-key"})
    other = client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-ops-key"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert other.status_code == 200


def test_authenticated_requests_log_usage(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app(api_keys_path, db_path))

    response = client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-ops-key"})

    assert response.status_code == 200
    rows = duckdb.connect(str(db_path)).execute(
        "SELECT tenant, key_name, endpoint FROM api_usage"
    ).fetchall()
    assert rows == [("acme", "Ops Agent", "/v1/metrics/revenue")]


def test_admin_endpoints_require_admin_key(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app(api_keys_path, db_path))

    response = client.get("/v1/admin/keys")

    assert response.status_code == 401


def test_admin_can_create_list_and_revoke_keys(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app(api_keys_path, db_path))
    headers = {"X-Admin-Key": "admin-secret"}

    created = client.post(
        "/v1/admin/keys",
        headers=headers,
        json={
            "name": "Support Agent",
            "tenant": "globex",
            "rate_limit_rpm": 7,
            "allowed_entity_types": ["user"],
        },
    )
    listed = client.get("/v1/admin/keys", headers=headers)
    new_key = created.json()["key"]
    deleted = client.delete(f"/v1/admin/keys/{new_key}", headers=headers)
    relisted = client.get("/v1/admin/keys", headers=headers)

    assert created.status_code == 201
    assert any(item["key"] == new_key for item in listed.json()["keys"])
    assert deleted.status_code == 204
    assert all(item["key"] != new_key for item in relisted.json()["keys"])


def test_admin_usage_returns_per_tenant_counts(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app(api_keys_path, db_path))
    headers = {"X-API-Key": "tenant-order-key"}

    client.get("/v1/entity/order/ORD-1", headers=headers)
    client.get("/v1/metrics/revenue", headers={"X-API-Key": "tenant-ops-key"})

    response = client.get("/v1/admin/usage", headers={"X-Admin-Key": "admin-secret"})

    assert response.status_code == 200
    assert response.json()["usage"] == [{"tenant": "acme", "requests_last_24h": 2}]
