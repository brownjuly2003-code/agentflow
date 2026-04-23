import time
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

import src.serving.api.auth.key_rotation as key_rotation_module
from src.serving.api.auth import AuthManager
from src.serving.api.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "pipeline.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
    monkeypatch.setenv("AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS", "30")

    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        (
            "keys:\n"
            '  - key: "rotation-acme-key"\n'
            '    name: "Rotation Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-04-10"\n'
        ),
        encoding="utf-8",
        newline="\n",
    )

    with TestClient(app) as c:
        manager = AuthManager(
            api_keys_path=api_keys_path,
            db_path=tmp_path / "usage.duckdb",
            admin_key="admin-secret",
        )
        manager.load()
        manager.ensure_usage_table()
        c.app.state.auth_manager = manager
        yield c
        manager.shutdown()


@pytest.fixture
def expiring_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "pipeline.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))
    monkeypatch.setenv("AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS", "1")

    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        (
            "keys:\n"
            '  - key: "rotation-acme-key"\n'
            '    name: "Rotation Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-04-10"\n'
        ),
        encoding="utf-8",
        newline="\n",
    )

    with TestClient(app) as c:
        manager = AuthManager(
            api_keys_path=api_keys_path,
            db_path=tmp_path / "usage.duckdb",
            admin_key="admin-secret",
        )
        manager.load()
        manager.ensure_usage_table()
        c.app.state.auth_manager = manager
        yield c
        manager.shutdown()


def test_rotation_endpoints_require_admin_key(client: TestClient):
    key_id = client.app.state.auth_manager.list_keys_with_usage()[0]["key_id"]

    rotate = client.post(f"/v1/admin/keys/{key_id}/rotate")
    status_response = client.get(f"/v1/admin/keys/{key_id}/rotation-status")
    revoke = client.post(f"/v1/admin/keys/{key_id}/revoke-old")

    assert rotate.status_code == 401
    assert status_response.status_code == 401
    assert revoke.status_code == 401


def test_rotation_status_is_idle_when_no_rotation_in_progress(client: TestClient):
    key_id = client.app.state.auth_manager.list_keys_with_usage()[0]["key_id"]

    response = client.get(
        f"/v1/admin/keys/{key_id}/rotation-status",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "phase": "idle",
        "old_key_active_until": None,
        "requests_on_old_key_last_hour": 0,
    }


def test_rotate_accepts_old_and_new_keys_during_grace_period(client: TestClient):
    key_id = client.app.state.auth_manager.list_keys_with_usage()[0]["key_id"]

    rotate = client.post(
        f"/v1/admin/keys/{key_id}/rotate",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert rotate.status_code == 200
    payload = rotate.json()
    assert payload["new_key"] != "rotation-acme-key"
    assert payload["expires_at"]

    old_response = client.get("/v1/metrics/revenue", headers={"X-API-Key": "rotation-acme-key"})
    new_response = client.get("/v1/metrics/revenue", headers={"X-API-Key": payload["new_key"]})

    assert old_response.status_code == 200
    assert new_response.status_code == 200


def test_rotation_status_retries_transient_usage_db_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    manager = client.app.state.auth_manager
    key_id = manager.list_keys_with_usage()[0]["key_id"]
    real_connect = key_rotation_module.duckdb.connect
    attempts = 0

    def flaky_connect(path: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise duckdb.IOException("usage db is locked")
        return real_connect(path)

    monkeypatch.setattr(key_rotation_module.duckdb, "connect", flaky_connect)

    response = client.get(
        f"/v1/admin/keys/{key_id}/rotation-status",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert response.status_code == 200
    assert response.json()["requests_on_old_key_last_hour"] == 0
    assert attempts >= 2


def test_rotation_status_counts_old_key_requests(client: TestClient):
    key_id = client.app.state.auth_manager.list_keys_with_usage()[0]["key_id"]
    rotate = client.post(
        f"/v1/admin/keys/{key_id}/rotate",
        headers={"X-Admin-Key": "admin-secret"},
    )
    new_key = rotate.json()["new_key"]

    client.get("/v1/metrics/revenue", headers={"X-API-Key": "rotation-acme-key"})
    client.get("/v1/entity/order/ORD-20260412-0001", headers={"X-API-Key": "rotation-acme-key"})
    client.get("/v1/metrics/revenue", headers={"X-API-Key": new_key})

    response = client.get(
        f"/v1/admin/keys/{key_id}/rotation-status",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert response.status_code == 200
    assert response.json()["phase"] == "grace_period"
    assert response.json()["old_key_active_until"] is not None
    assert response.json()["requests_on_old_key_last_hour"] == 2


def test_revoke_old_key_invalidates_only_previous_key(client: TestClient):
    key_id = client.app.state.auth_manager.list_keys_with_usage()[0]["key_id"]
    rotate = client.post(
        f"/v1/admin/keys/{key_id}/rotate",
        headers={"X-Admin-Key": "admin-secret"},
    )
    new_key = rotate.json()["new_key"]

    revoke = client.post(
        f"/v1/admin/keys/{key_id}/revoke-old",
        headers={"X-Admin-Key": "admin-secret"},
    )
    old_response = client.get("/v1/metrics/revenue", headers={"X-API-Key": "rotation-acme-key"})
    new_response = client.get("/v1/metrics/revenue", headers={"X-API-Key": new_key})

    assert revoke.status_code == 200
    assert revoke.json() == {"revoked": True}
    assert old_response.status_code == 401
    assert new_response.status_code == 200


def test_rotate_rejects_second_rotation_during_grace_period(client: TestClient):
    key_id = client.app.state.auth_manager.list_keys_with_usage()[0]["key_id"]

    first = client.post(
        f"/v1/admin/keys/{key_id}/rotate",
        headers={"X-Admin-Key": "admin-secret"},
    )
    second = client.post(
        f"/v1/admin/keys/{key_id}/rotate",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_expired_grace_period_revokes_old_key_automatically(expiring_client: TestClient):
    key_id = expiring_client.app.state.auth_manager.list_keys_with_usage()[0]["key_id"]
    rotate = expiring_client.post(
        f"/v1/admin/keys/{key_id}/rotate",
        headers={"X-Admin-Key": "admin-secret"},
    )
    new_key = rotate.json()["new_key"]

    deadline = time.monotonic() + 3
    status_response = expiring_client.get(
        f"/v1/admin/keys/{key_id}/rotation-status",
        headers={"X-Admin-Key": "admin-secret"},
    )
    while time.monotonic() < deadline:
        status_response = expiring_client.get(
            f"/v1/admin/keys/{key_id}/rotation-status",
            headers={"X-Admin-Key": "admin-secret"},
        )
        if status_response.status_code == 200 and status_response.json()["phase"] == "idle":
            break
        time.sleep(0.1)

    old_response = expiring_client.get(
        "/v1/metrics/revenue",
        headers={"X-API-Key": "rotation-acme-key"},
    )
    new_response = expiring_client.get(
        "/v1/metrics/revenue",
        headers={"X-API-Key": new_key},
    )

    assert rotate.status_code == 200
    assert old_response.status_code == 401
    assert status_response.status_code == 200
    assert status_response.json()["phase"] == "idle"
    assert new_response.status_code == 200
