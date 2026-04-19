from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager
from src.serving.api.main import app

pytestmark = pytest.mark.integration


def _write_api_keys(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "keys:\n"
            "  - key: \"admin-ui-acme-key\"\n"
            "    name: \"Admin UI Agent\"\n"
            "    tenant: \"acme\"\n"
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            "    created_at: \"2026-04-10\"\n"
        ),
        encoding="utf-8",
        newline="\n",
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "pipeline.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "usage.duckdb"))

    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    _write_api_keys(api_keys_path)

    with TestClient(app) as c:
        manager = AuthManager(
            api_keys_path=api_keys_path,
            db_path=tmp_path / "usage.duckdb",
            admin_key="admin-secret",
        )
        manager.load()
        manager.ensure_usage_table()
        c.app.state.auth_manager = manager
        c.get("/v1/metrics/revenue", headers={"X-API-Key": "admin-ui-acme-key"})
        yield c
        manager.shutdown()


def test_admin_ui_requires_admin_key(client: TestClient):
    response = client.get("/admin/")

    assert response.status_code == 401


def test_admin_ui_renders_dashboard(client: TestClient):
    response = client.get("/admin/", headers={"X-Admin-Key": "admin-secret"})

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "AgentFlow Admin" in response.text
    assert "System Summary" in response.text


def test_admin_ui_partial_renders_summary(client: TestClient):
    response = client.get(
        "/admin/partials/summary",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert response.status_code == 200
    assert "System Summary" in response.text
