"""F-02 B: API key store may be a read-only Secret mount (Helm default).

These tests pin that ``AuthManager.load()`` still starts against that mount,
that mutating admin endpoints answer 409 (not 500), and that a writable store
keeps the existing lifecycle.

Read-only setup uses ``chmod(S_IRUSR)``. On this Windows host that sets the
NTFS read-only attribute and ``Path.write_text`` raises ``PermissionError``
(asserted by ``test_readonly_mechanism_blocks_writes``). If that assertion
fails on another host, do not weaken it — patch the write seam instead.
"""

from __future__ import annotations

import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentflow_runtime.serving.api.auth import AuthManager, build_auth_middleware
from agentflow_runtime.serving.api.auth.manager import KEY_STORE_READONLY_DETAIL
from agentflow_runtime.serving.api.routers.admin import router as admin_router

SEED_WITHOUT_KEY_IDS = (
    "keys:\n"
    '  - key: "readonly-acme-key"\n'
    '    name: "RO Agent"\n'
    '    tenant: "acme"\n'
    "    rate_limit_rpm: 100\n"
    "    allowed_entity_types: null\n"
    '    created_at: "2026-04-10"\n'
    '    previous_key_hash: "expired-hash"\n'
    '    previous_key_active_until: "2020-01-01T00:00:00+00:00"\n'
)

SEED_WITH_KEY_IDS = (
    "keys:\n"
    '  - key_id: "acme-ops-abcd"\n'
    '    key: "tenant-ops-key"\n'
    '    name: "Ops Agent"\n'
    '    tenant: "acme"\n'
    "    rate_limit_rpm: 120\n"
    "    allowed_entity_types: null\n"
    '    created_at: "2026-04-10"\n'
)

_SKIP_EVENT = "api_key_store_write_skipped_readonly"
_ADMIN_HEADERS = {"X-Admin-Key": "admin-secret"}
_CREATE_PAYLOAD = {
    "name": "Support Agent",
    "tenant": "globex",
    "rate_limit_rpm": 7,
}


@pytest.fixture(autouse=True)
def _uncached_auth_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentflow_runtime.serving.api import auth as auth_package

    monkeypatch.setattr(auth_package, "logger", structlog.get_logger())


@contextmanager
def file_made_read_only(path: Path) -> Iterator[None]:
    path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        yield
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)


def _write_keys(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _build_manager(api_keys_path: Path, db_path: Path) -> AuthManager:
    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        admin_key="admin-secret",
    )
    manager.security_policy.bcrypt_rounds = 4
    manager.ensure_usage_table()
    return manager


def _build_app(api_keys_path: Path, db_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _build_manager(api_keys_path, db_path)
    app.state.auth_manager.load()
    app.state.auth_manager.ensure_usage_table()
    app.middleware("http")(build_auth_middleware())
    app.include_router(admin_router, prefix="/v1")
    return app


def test_readonly_mechanism_blocks_writes(tmp_path: Path) -> None:
    """chmod must actually reject writes on this host; a silent pass is invalid."""
    path = tmp_path / "probe.yaml"
    path.write_text("keys: []\n", encoding="utf-8")
    with file_made_read_only(path):
        with pytest.raises(PermissionError):
            path.write_text("keys: []\n", encoding="utf-8")


def test_load_against_readonly_store_does_not_raise_and_normalises_ids(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITHOUT_KEY_IDS)
    original = api_keys_path.read_text(encoding="utf-8")
    manager = _build_manager(api_keys_path, tmp_path / "usage.duckdb")
    try:
        with file_made_read_only(api_keys_path):
            manager.load()
            assert manager.key_store_writable is False
            assert manager.configured_key_count == 1
            loaded = manager.list_keys_with_usage()
            assert loaded[0]["key_id"]
            assert loaded[0]["key_id"] is not None
            assert manager.authenticate("readonly-acme-key") is not None
            assert loaded[0]["rotation_phase"] == "idle"
            assert api_keys_path.read_text(encoding="utf-8") == original
    finally:
        manager.shutdown()


def test_readonly_skip_warning_emitted_once_per_manager(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITHOUT_KEY_IDS)
    manager = _build_manager(api_keys_path, tmp_path / "usage.duckdb")
    try:
        with file_made_read_only(api_keys_path), structlog.testing.capture_logs() as events:
            manager.load()
            manager.load()
            manager.load()
        warnings = [event for event in events if event.get("event") == _SKIP_EVENT]
        assert len(warnings) == 1
        assert warnings[0].get("path") == str(api_keys_path)
        assert "readonly-acme-key" not in str(warnings[0])
    finally:
        manager.shutdown()


def test_post_admin_keys_returns_409_when_store_readonly(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITH_KEY_IDS)
    with file_made_read_only(api_keys_path):
        app = _build_app(api_keys_path, tmp_path / "usage.duckdb")
        client = TestClient(app)
        response = client.post("/v1/admin/keys", headers=_ADMIN_HEADERS, json=_CREATE_PAYLOAD)
        assert response.status_code == 409
        assert response.json()["detail"] == KEY_STORE_READONLY_DETAIL
        assert "readonly-acme-key" not in response.text
        assert "tenant-ops-key" not in response.text
        app.state.auth_manager.shutdown()


def test_post_admin_keys_rotate_returns_409_when_store_readonly(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITH_KEY_IDS)
    with file_made_read_only(api_keys_path):
        app = _build_app(api_keys_path, tmp_path / "usage.duckdb")
        client = TestClient(app)
        response = client.post(
            "/v1/admin/keys/acme-ops-abcd/rotate",
            headers=_ADMIN_HEADERS,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == KEY_STORE_READONLY_DETAIL
        assert "tenant-ops-key" not in response.text
        app.state.auth_manager.shutdown()


def test_delete_admin_keys_returns_409_when_store_readonly(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITH_KEY_IDS)
    with file_made_read_only(api_keys_path):
        app = _build_app(api_keys_path, tmp_path / "usage.duckdb")
        client = TestClient(app)
        response = client.delete("/v1/admin/keys/acme-ops-abcd", headers=_ADMIN_HEADERS)
        assert response.status_code == 409
        assert response.json()["detail"] == KEY_STORE_READONLY_DETAIL
        assert "tenant-ops-key" not in response.text
        app.state.auth_manager.shutdown()


def test_post_admin_keys_revoke_old_returns_409_when_store_readonly(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITH_KEY_IDS)
    with file_made_read_only(api_keys_path):
        app = _build_app(api_keys_path, tmp_path / "usage.duckdb")
        client = TestClient(app)
        response = client.post(
            "/v1/admin/keys/acme-ops-abcd/revoke-old",
            headers=_ADMIN_HEADERS,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == KEY_STORE_READONLY_DETAIL
        app.state.auth_manager.shutdown()


def test_get_admin_keys_returns_200_when_store_readonly(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITH_KEY_IDS)
    with file_made_read_only(api_keys_path):
        app = _build_app(api_keys_path, tmp_path / "usage.duckdb")
        client = TestClient(app)
        response = client.get("/v1/admin/keys", headers=_ADMIN_HEADERS)
        assert response.status_code == 200
        keys = response.json()["keys"]
        assert keys[0]["key_id"] == "acme-ops-abcd"
        assert "key" not in keys[0]
        app.state.auth_manager.shutdown()


def test_writable_store_keeps_create_rotate_delete_and_list(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITH_KEY_IDS)
    app = _build_app(api_keys_path, tmp_path / "usage.duckdb")
    try:
        assert app.state.auth_manager.key_store_writable is True
        client = TestClient(app)
        created = client.post("/v1/admin/keys", headers=_ADMIN_HEADERS, json=_CREATE_PAYLOAD)
        assert created.status_code == 201
        new_key_id = created.json()["key_id"]
        assert created.json()["key"]
        listed = client.get("/v1/admin/keys", headers=_ADMIN_HEADERS)
        assert listed.status_code == 200
        assert any(item["key_id"] == new_key_id for item in listed.json()["keys"])
        rotated = client.post(
            f"/v1/admin/keys/{new_key_id}/rotate",
            headers=_ADMIN_HEADERS,
        )
        assert rotated.status_code == 200
        assert rotated.json()["new_key"]
        deleted = client.delete(f"/v1/admin/keys/{new_key_id}", headers=_ADMIN_HEADERS)
        assert deleted.status_code == 204
        relisted = client.get("/v1/admin/keys", headers=_ADMIN_HEADERS)
        assert all(item["key_id"] != new_key_id for item in relisted.json()["keys"])
    finally:
        app.state.auth_manager.shutdown()


def test_writable_load_persists_normalised_key_ids(tmp_path: Path) -> None:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITHOUT_KEY_IDS)
    manager = _build_manager(api_keys_path, tmp_path / "usage.duckdb")
    try:
        manager.load()
        assert manager.key_store_writable is True
        text = api_keys_path.read_text(encoding="utf-8")
        assert "key_id:" in text
        assert "previous_key_hash" not in text
        assert all(item["key_id"] for item in manager.list_keys_with_usage())
    finally:
        manager.shutdown()


def test_permission_error_during_write_maps_to_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mount flipped after a writable probe: PermissionError must be 409, not 500."""
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_keys(api_keys_path, SEED_WITH_KEY_IDS)
    app = _build_app(api_keys_path, tmp_path / "usage.duckdb")
    try:
        assert app.state.auth_manager.key_store_writable is True
        target = api_keys_path.resolve()
        original = Path.write_text

        def _boom(self: Path, *args: object, **kwargs: object) -> int:
            if Path(self).resolve() == target:
                raise PermissionError("simulated read-only remount")
            return original(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "write_text", _boom)
        client = TestClient(app)
        response = client.post("/v1/admin/keys", headers=_ADMIN_HEADERS, json=_CREATE_PAYLOAD)
        assert response.status_code == 409
        assert response.json()["detail"] == KEY_STORE_READONLY_DETAIL
        assert "simulated read-only remount" not in response.text
    finally:
        app.state.auth_manager.shutdown()
