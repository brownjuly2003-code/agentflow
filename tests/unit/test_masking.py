from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import src.serving.api.routers.agent_query as agent_query_module
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.masking import PiiMasker
from src.serving.semantic_layer.catalog import DataCatalog

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "pii_fields.yaml"


def _write_pii_config(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def _reset_router_masker(monkeypatch, config_path: Path) -> None:
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(config_path))
    monkeypatch.setattr(agent_query_module, "_PII_MASKER", None, raising=False)


class EngineStub:
    def __init__(self, payload: dict):
        self.payload = payload

    def get_entity(self, entity_type: str, entity_id: str) -> dict:
        return dict(self.payload)


def _build_client(payload: dict, tenant: str = "acme") -> TestClient:
    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.state.query_engine = EngineStub(payload)

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        request.state.tenant_key = SimpleNamespace(tenant=tenant)
        return await call_next(request)

    app.include_router(agent_router, prefix="/v1")
    return TestClient(app)


def test_masker_partially_masks_email_from_default_config():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    masked = masker.mask("user", {"email": "jane@example.com"}, tenant="acme")

    assert masked["email"] == "j***@example.com"


def test_masker_partially_masks_phone_from_default_config():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    masked = masker.mask("user", {"phone": "555-123-4567"}, tenant="acme")

    assert masked["phone"] == "***-***-4567"


def test_masker_partially_masks_full_name_from_default_config():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    masked = masker.mask("user", {"full_name": "Jane Doe"}, tenant="acme")

    assert masked["full_name"] == "J*** D***"


def test_masker_hashes_ip_addresses_from_default_config():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)

    masked = masker.mask("user", {"ip_address": "203.0.113.10"}, tenant="acme")

    assert masked["ip_address"] == hashlib.sha256(b"203.0.113.10").hexdigest()[:12]


def test_masker_uses_custom_config_as_single_source_of_truth(tmp_path: Path):
    config_path = _write_pii_config(
        tmp_path / "pii_fields.yaml",
        """
        masking:
          default_strategy: partial
          entity_fields:
            order:
              - field: user_id
                strategy: full
          pii_exempt_tenants: []
        """,
    )
    masker = PiiMasker(config_path)

    masked = masker.mask("order", {"user_id": "USR-1", "status": "delivered"}, tenant="acme")

    assert masked == {"user_id": "***", "status": "delivered"}


def test_masker_skips_pii_exempt_tenant():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)
    payload = {"email": "jane@example.com", "full_name": "Jane Doe"}

    masked = masker.mask("user", payload, tenant="internal-analytics")

    assert masked == payload


def test_masker_ignores_missing_fields():
    masker = PiiMasker(DEFAULT_CONFIG_PATH)
    payload = {"status": "delivered"}

    masked = masker.mask("order", payload, tenant="acme")

    assert masked == payload


def test_entity_endpoint_masks_data_and_sets_header(monkeypatch):
    _reset_router_masker(monkeypatch, DEFAULT_CONFIG_PATH)
    client = _build_client(
        {
            "user_id": "USR-1",
            "email": "jane@example.com",
            "phone": "555-123-4567",
            "full_name": "Jane Doe",
            "ip_address": "203.0.113.10",
            "_last_updated": "2026-04-10T12:00:00+00:00",
        }
    )

    response = client.get("/v1/entity/user/USR-1")

    assert response.status_code == 200
    assert response.headers["X-PII-Masked"] == "true"
    assert response.json()["data"]["email"] == "j***@example.com"


def test_entity_endpoint_skips_masking_for_exempt_tenant(monkeypatch):
    _reset_router_masker(monkeypatch, DEFAULT_CONFIG_PATH)
    client = _build_client(
        {
            "user_id": "USR-1",
            "email": "jane@example.com",
            "full_name": "Jane Doe",
            "_last_updated": "2026-04-10T12:00:00+00:00",
        },
        tenant="internal-analytics",
    )

    response = client.get("/v1/entity/user/USR-1")

    assert response.status_code == 200
    assert "X-PII-Masked" not in response.headers
    assert response.json()["data"]["email"] == "jane@example.com"
