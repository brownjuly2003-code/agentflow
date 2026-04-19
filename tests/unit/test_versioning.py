from __future__ import annotations

import importlib
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

import src.serving.api.routers.agent_query as agent_query_module
from src.serving.api.versioning import ApiVersionRegistry, ResponseTransformer
from src.serving.cache import QueryCache


def _write_api_keys(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "keys:\n"
            "  - key: \"acme-key\"\n"
            "    name: \"Acme Agent\"\n"
            "    tenant: \"acme\"\n"
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            "    created_at: \"2026-04-11\"\n"
        ),
        encoding="utf-8",
        newline="\n",
    )


def _write_tenants(path: Path, *, pin: str | None = "2026-01-01") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pin_line = f"    api_version_pin: \"{pin}\"\n" if pin is not None else ""
    path.write_text(
        (
            "tenants:\n"
            "  - id: acme\n"
            "    display_name: \"Acme Corp\"\n"
            "    kafka_topic_prefix: \"acme\"\n"
            "    duckdb_schema: \"acme\"\n"
            "    max_events_per_day: 1000000\n"
            "    max_api_keys: 10\n"
            "    allowed_entity_types: null\n"
            f"{pin_line}"
        ),
        encoding="utf-8",
        newline="\n",
    )


def _write_api_versions(path: Path, content: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            content
            or (
                "versions:\n"
                "  - date: \"2026-01-01\"\n"
                "    status: stable\n"
                "    changes: []\n"
                "  - date: \"2026-04-11\"\n"
                "    status: latest\n"
                "    changes:\n"
                "      - type: additive\n"
                "        description: \"Added meta.is_historical to entity responses\"\n"
                "      - type: additive\n"
                "        description: \"Added X-PII-Masked response header\"\n"
            )
        ),
        encoding="utf-8",
        newline="\n",
    )


def _write_pii_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "masking:\n"
            "  default_strategy: partial\n"
            "  entity_fields:\n"
            "    order:\n"
            "      - field: user_id\n"
            "        strategy: full\n"
            "  pii_exempt_tenants: []\n"
        ),
        encoding="utf-8",
        newline="\n",
    )


def _seed_tenant_data(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE SCHEMA IF NOT EXISTS acme")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS acme.orders_v2 (
                order_id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                status VARCHAR,
                total_amount DECIMAL(10,2),
                currency VARCHAR,
                created_at TIMESTAMP
            )
            """
        )
        conn.execute("DELETE FROM acme.orders_v2")
        conn.execute(
            """
            INSERT INTO acme.orders_v2 VALUES
            ('ORD-ACME', 'USR-ACME', 'delivered', 80.00, 'USD', NOW())
            """
        )
    finally:
        conn.close()


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    tenant_pin: str = "2026-01-01",
    versions_content: str | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    db_path = tmp_path / "versioning.duckdb"
    usage_db_path = tmp_path / "usage.duckdb"
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    tenants_path = tmp_path / "config" / "tenants.yaml"
    versions_path = tmp_path / "config" / "api_versions.yaml"
    pii_path = tmp_path / "config" / "pii_fields.yaml"

    _write_api_keys(api_keys_path)
    _write_tenants(tenants_path, pin=tenant_pin)
    _write_api_versions(versions_path, versions_content)
    _write_pii_config(pii_path)
    _seed_tenant_data(db_path)

    monkeypatch.setenv("DUCKDB_PATH", str(db_path))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(usage_db_path))
    monkeypatch.setenv("AGENTFLOW_API_KEYS_FILE", str(api_keys_path))
    monkeypatch.setenv("AGENTFLOW_TENANTS_FILE", str(tenants_path))
    monkeypatch.setenv("AGENTFLOW_API_VERSIONS_FILE", str(versions_path))
    monkeypatch.setenv("AGENTFLOW_PII_CONFIG", str(pii_path))
    monkeypatch.setattr(agent_query_module, "_PII_MASKER", None, raising=False)

    main_module = importlib.import_module("src.serving.api.main")
    main_module = importlib.reload(main_module)
    return TestClient(
        main_module.app,
        raise_server_exceptions=raise_server_exceptions,
    )


def test_registry_loads_versions_and_exposes_latest(tmp_path: Path) -> None:
    config_path = tmp_path / "api_versions.yaml"
    _write_api_versions(config_path)

    registry = ApiVersionRegistry(config_path)

    assert registry.latest().date == "2026-04-11"
    assert registry.get("2026-01-01").status == "stable"


def test_transformer_removes_meta_is_historical_for_older_versions(tmp_path: Path) -> None:
    config_path = tmp_path / "api_versions.yaml"
    _write_api_versions(config_path)
    transformer = ResponseTransformer(ApiVersionRegistry(config_path))

    transformed = transformer.transform(
        {
            "entity_type": "order",
            "entity_id": "ORD-1",
            "data": {"order_id": "ORD-1"},
            "meta": {"is_historical": False, "freshness_seconds": 12.0},
        },
        from_version="2026-04-11",
        to_version="2026-01-01",
    )

    assert "is_historical" not in transformed["meta"]
    assert transformed["meta"]["freshness_seconds"] == 12.0


def test_transformer_removes_new_headers_for_older_versions(tmp_path: Path) -> None:
    config_path = tmp_path / "api_versions.yaml"
    _write_api_versions(config_path)
    transformer = ResponseTransformer(ApiVersionRegistry(config_path))

    transformed = transformer.transform_headers(
        {"X-PII-Masked": "true", "X-Other": "keep"},
        from_version="2026-04-11",
        to_version="2026-01-01",
    )

    assert "X-PII-Masked" not in transformed
    assert transformed["X-Other"] == "keep"


def test_transformer_removes_arbitrary_added_fields_for_older_versions(tmp_path: Path) -> None:
    config_path = tmp_path / "api_versions.yaml"
    _write_api_versions(
        config_path,
        (
            "versions:\n"
            "  - date: \"2026-01-01\"\n"
            "    status: stable\n"
            "    changes: []\n"
            "  - date: \"2026-04-11\"\n"
            "    status: latest\n"
            "    changes:\n"
            "      - type: additive\n"
            "        description: \"Added meta.as_of to entity responses\"\n"
            "      - type: additive\n"
            "        description: \"Added components to metric responses\"\n"
        ),
    )
    transformer = ResponseTransformer(ApiVersionRegistry(config_path))

    transformed = transformer.transform(
        {
            "components": {"source": "sql"},
            "meta": {
                "as_of": "2026-04-11T00:00:00Z",
                "freshness_seconds": 12.0,
            },
        },
        from_version="2026-04-11",
        to_version="2026-01-01",
    )

    assert "components" not in transformed
    assert transformed["meta"]["freshness_seconds"] == 12.0
    assert "as_of" not in transformed["meta"]


def test_tenant_pin_applies_when_request_header_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _build_client(monkeypatch, tmp_path) as client:
        response = client.get("/v1/entity/order/ORD-ACME", headers={"X-API-Key": "acme-key"})

    assert response.status_code == 200
    assert response.headers["X-AgentFlow-Version"] == "2026-01-01"
    assert "is_historical" not in response.json()["meta"]


def test_request_header_overrides_tenant_pin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _build_client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/v1/entity/order/ORD-ACME",
            headers={
                "X-API-Key": "acme-key",
                "X-AgentFlow-Version": "2026-04-11",
            },
        )

    assert response.status_code == 200
    assert response.headers["X-AgentFlow-Version"] == "2026-04-11"
    assert response.headers["X-AgentFlow-Latest-Version"] == "2026-04-11"
    assert response.json()["meta"]["is_historical"] is False


def test_invalid_tenant_pin_returns_400_instead_of_500(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _build_client(
        monkeypatch,
        tmp_path,
        tenant_pin="2099-99-99",
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/v1/entity/order/ORD-ACME", headers={"X-API-Key": "acme-key"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported API version: 2099-99-99"}


def test_missing_tenant_pin_falls_back_to_latest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _build_client(monkeypatch, tmp_path, tenant_pin=None) as client:
        response = client.get("/v1/entity/order/ORD-ACME", headers={"X-API-Key": "acme-key"})

    assert response.status_code == 200
    assert response.headers["X-AgentFlow-Version"] == "2026-04-11"
    assert response.json()["meta"]["is_historical"] is False


def test_metric_cache_is_scoped_by_requested_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.data: dict[str, str] = {}

        async def get(self, key: str):
            return self.data.get(key)

        async def setex(self, key: str, ttl, value: str) -> None:
            self.data[key] = value

        async def keys(self, pattern: str):
            prefix = pattern[:-1] if pattern.endswith("*") else pattern
            return [key for key in self.data if key.startswith(prefix)]

        async def delete(self, *keys: str) -> None:
            for key in keys:
                self.data.pop(key, None)

        async def aclose(self) -> None:
            return None

    with _build_client(monkeypatch, tmp_path) as client:
        client.app.state.query_cache = QueryCache(redis_client=FakeRedis())
        pinned = client.get("/v1/metrics/revenue?window=24h", headers={"X-API-Key": "acme-key"})
        latest = client.get(
            "/v1/metrics/revenue?window=24h",
            headers={
                "X-API-Key": "acme-key",
                "X-AgentFlow-Version": "2026-04-11",
            },
        )

    assert pinned.status_code == 200
    assert pinned.headers["X-Cache"] == "MISS"
    assert "is_historical" not in pinned.json()["meta"]
    assert latest.status_code == 200
    assert latest.headers["X-Cache"] == "MISS"
    assert latest.json()["meta"]["is_historical"] is False


def test_older_versions_hide_new_pii_header(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _build_client(monkeypatch, tmp_path) as client:
        response = client.get("/v1/entity/order/ORD-ACME", headers={"X-API-Key": "acme-key"})

    assert response.status_code == 200
    assert "X-PII-Masked" not in response.headers
    assert response.json()["data"]["user_id"] == "***"


def test_deprecated_versions_emit_warning_header(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    versions_content = (
        "versions:\n"
        "  - date: \"2025-01-01\"\n"
        "    status: stable\n"
        "    changes: []\n"
        "  - date: \"2026-04-11\"\n"
        "    status: latest\n"
        "    changes:\n"
        "      - type: additive\n"
        "        description: \"Added meta.is_historical to entity responses\"\n"
    )

    with _build_client(
        monkeypatch,
        tmp_path,
        tenant_pin="2025-01-01",
        versions_content=versions_content,
    ) as client:
        response = client.get("/v1/entity/order/ORD-ACME", headers={"X-API-Key": "acme-key"})

    assert response.status_code == 200
    assert response.headers["X-AgentFlow-Deprecated"] == "true"
    assert "unsupported after 2026-01-01" in response.headers["X-AgentFlow-Deprecation-Warning"]


def test_changelog_endpoint_returns_version_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with _build_client(monkeypatch, tmp_path) as client:
        response = client.get("/v1/changelog", headers={"X-API-Key": "acme-key"})

    assert response.status_code == 200
    assert response.json()["latest_version"] == "2026-04-11"
    assert response.json()["versions"][0]["date"] == "2026-01-01"
