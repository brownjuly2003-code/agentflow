import sys
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from agentflow.client import AgentFlowClient

from src.serving.api.main import app

pytestmark = pytest.mark.integration


def _write_contract(
    contracts_dir: Path,
    name: str,
    payload: dict,
) -> None:
    contracts_dir.mkdir(parents=True, exist_ok=True)
    (contracts_dir / name).write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def _install_request_stub(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    def _request(self, method, url, **kwargs):
        result = handler(method, str(url), **kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(httpx.Client, "request", _request)


@pytest.fixture
def contracts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "config" / "contracts"
    _write_contract(
        directory,
        "order.v1.yaml",
        {
            "entity": "order",
            "version": "1",
            "released": "2026-04-11",
            "status": "deprecated",
            "fields": [
                {"name": "order_id", "type": "string", "required": True},
                {"name": "status", "type": "enum", "required": True},
                {"name": "total_amount", "type": "float", "required": True, "unit": "USD"},
                {"name": "currency", "type": "string", "required": True},
                {"name": "user_id", "type": "string", "required": True},
                {"name": "created_at", "type": "datetime", "required": True},
                {"name": "legacy_id", "type": "string", "required": False},
            ],
            "breaking_changes": [],
        },
    )
    _write_contract(
        directory,
        "order.v2.yaml",
        {
            "entity": "order",
            "version": "2",
            "released": "2026-04-12",
            "status": "stable",
            "fields": [
                {"name": "order_id", "type": "string", "required": True},
                {"name": "status", "type": "enum", "required": True},
                {"name": "total_amount", "type": "float", "required": True, "unit": "USD"},
                {"name": "discount_amount", "type": "float", "required": False, "unit": "USD"},
                {"name": "currency", "type": "string", "required": True},
                {"name": "user_id", "type": "string", "required": True},
                {"name": "created_at", "type": "datetime", "required": True},
            ],
            "breaking_changes": [],
        },
    )
    _write_contract(
        directory,
        "metric.revenue.v1.yaml",
        {
            "entity": "metric.revenue",
            "version": "1",
            "released": "2026-04-11",
            "status": "stable",
            "fields": [
                {"name": "value", "type": "float", "required": True, "unit": "USD"},
                {"name": "unit", "type": "string", "required": True},
                {"name": "window", "type": "string", "required": True},
                {"name": "computed_at", "type": "datetime", "required": True},
            ],
            "breaking_changes": [],
        },
    )
    return directory


@pytest.fixture
def client(
    contracts_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("AGENTFLOW_CONTRACTS_DIR", str(contracts_dir))
    monkeypatch.setenv("AGENTFLOW_API_KEYS_FILE", str(tmp_path / "missing-api-keys.yaml"))
    monkeypatch.delenv("AGENTFLOW_API_KEYS", raising=False)
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "contracts.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "contracts-api.duckdb"))

    with TestClient(app) as test_client:
        yield test_client


def test_contracts_endpoint_lists_all_versions(client: TestClient):
    response = client.get("/v1/contracts")

    assert response.status_code == 200
    data = response.json()
    assert [item["entity"] for item in data["contracts"]] == [
        "metric.revenue",
        "order",
        "order",
    ]
    assert [item["version"] for item in data["contracts"]] == ["1", "1", "2"]


def test_contracts_endpoint_returns_latest_stable_schema(client: TestClient):
    response = client.get("/v1/contracts/order")

    assert response.status_code == 200
    data = response.json()
    assert data["entity"] == "order"
    assert data["version"] == "2"
    assert data["status"] == "stable"
    assert any(field["name"] == "discount_amount" for field in data["fields"])


def test_contracts_endpoint_returns_specific_version(client: TestClient):
    response = client.get("/v1/contracts/order/1")

    assert response.status_code == 200
    data = response.json()
    assert data["entity"] == "order"
    assert data["version"] == "1"
    assert any(field["name"] == "legacy_id" for field in data["fields"])


def test_contract_diff_classifies_breaking_and_additive_changes(client: TestClient):
    response = client.get("/v1/contracts/order/diff/1/2")

    assert response.status_code == 200
    data = response.json()
    assert data["entity"] == "order"
    assert data["from_version"] == "1"
    assert data["to_version"] == "2"
    assert data["breaking_changes"] == [
        {"type": "field_removed", "field": "legacy_id", "severity": "breaking"},
    ]
    assert data["additive_changes"] == [
        {"type": "field_added", "field": "discount_amount", "severity": "non_breaking"},
    ]


def test_catalog_embeds_contract_versions(client: TestClient):
    response = client.get("/v1/catalog")

    assert response.status_code == 200
    data = response.json()
    assert data["entities"]["order"]["contract_version"] == "2"
    assert data["metrics"]["revenue"]["contract_version"] == "1"


def test_sdk_contract_pinning_fetches_contract_and_ignores_extra_fields(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []

    def handler(method, url, **kwargs):
        calls.append(f"{method} {url}")
        if url == "/v1/contracts/order/1":
            return httpx.Response(
                200,
                json={
                    "entity": "order",
                    "version": "1",
                    "released": "2026-04-11",
                    "status": "stable",
                    "fields": [
                        {"name": "order_id", "type": "string", "required": True},
                        {"name": "status", "type": "string", "required": True},
                        {"name": "total_amount", "type": "float", "required": True},
                        {"name": "currency", "type": "string", "required": True},
                        {"name": "user_id", "type": "string", "required": True},
                        {"name": "created_at", "type": "datetime", "required": True},
                    ],
                    "breaking_changes": [],
                },
            )
        if url == "/v1/entity/order/ORD-1":
            return httpx.Response(
                200,
                json={
                    "entity_type": "order",
                    "entity_id": "ORD-1",
                    "data": {
                        "order_id": "ORD-1",
                        "user_id": "USR-1",
                        "status": "pending",
                        "total_amount": "19.99",
                        "currency": "USD",
                        "created_at": "2026-04-11T10:00:00Z",
                        "discount_amount": "2.50",
                    },
                    "last_updated": None,
                    "freshness_seconds": None,
                },
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    _install_request_stub(monkeypatch, handler)

    client = AgentFlowClient(
        "http://example.com",
        api_key="test-key",
        contract_version="order:v1",
    )
    order = client.get_order("ORD-1")

    assert order.order_id == "ORD-1"
    assert calls == [
        "GET /v1/entity/order/ORD-1",
        "GET /v1/contracts/order/1",
    ]
