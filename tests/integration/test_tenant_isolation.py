import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.ingestion.tenant_router import TenantRouter
from src.serving.api.main import app
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.cache import QueryCache
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine

pytestmark = pytest.mark.integration


def _write_api_keys(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "keys:\n"
            '  - key: "acme-key"\n'
            '    name: "Acme Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-04-11"\n'
            '  - key: "demo-key"\n'
            '    name: "Demo Agent"\n'
            '    tenant: "demo"\n'
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-04-11"\n'
        ),
        encoding="utf-8",
        newline="\n",
    )


def _write_tenants(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "tenants:\n"
            "  - id: acme\n"
            '    display_name: "Acme Corp"\n'
            '    kafka_topic_prefix: "acme"\n'
            '    duckdb_schema: "acme"\n'
            "    max_events_per_day: 1000000\n"
            "    max_api_keys: 10\n"
            "    allowed_entity_types: null\n"
            "  - id: demo\n"
            '    display_name: "Demo Tenant"\n'
            '    kafka_topic_prefix: "demo"\n'
            '    duckdb_schema: "demo"\n'
            "    max_events_per_day: 10000\n"
            "    max_api_keys: 2\n"
            "    allowed_entity_types:\n"
            '      - "order"\n'
            '      - "product"\n'
        ),
        encoding="utf-8",
        newline="\n",
    )


def _seed_tenant_data(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))
    try:
        for schema in ("acme", "demo"):
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.orders_v2 (
                    order_id VARCHAR PRIMARY KEY,
                    user_id VARCHAR,
                    status VARCHAR,
                    total_amount DECIMAL(10,2),
                    currency VARCHAR,
                    created_at TIMESTAMP
                )
                """
            )
            conn.execute(f"DELETE FROM {schema}.orders_v2")

        conn.execute(
            """
            INSERT INTO acme.orders_v2 VALUES
            ('ORD-SHARED', 'USR-ACME', 'confirmed', 125.50, 'USD', NOW()),
            ('ORD-ACME', 'USR-ACME-2', 'delivered', 80.00, 'USD', NOW())
            """
        )
        conn.execute(
            """
            INSERT INTO demo.orders_v2 VALUES
            ('ORD-SHARED', 'USR-DEMO', 'confirmed', 15.00, 'USD', NOW()),
            ('ORD-DEMO', 'USR-DEMO-2', 'pending', 25.00, 'USD', NOW())
            """
        )
    finally:
        conn.close()


@pytest.fixture
def tenant_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    db_path = tmp_path / "tenant-isolation.duckdb"
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    tenants_path = tmp_path / "config" / "tenants.yaml"
    _write_api_keys(api_keys_path)
    _write_tenants(tenants_path)
    _seed_tenant_data(db_path)
    return db_path, api_keys_path, tenants_path


@pytest.fixture
def client(tenant_paths: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch):
    db_path, api_keys_path, tenants_path = tenant_paths
    usage_db_path = db_path.parent / "usage.duckdb"

    monkeypatch.setenv("DUCKDB_PATH", str(db_path))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(usage_db_path))
    monkeypatch.setenv("AGENTFLOW_API_KEYS_FILE", str(api_keys_path))
    monkeypatch.setenv("AGENTFLOW_TENANTS_FILE", str(tenants_path))

    with TestClient(app) as test_client:
        yield test_client


def test_tenant_router_prefixes_topics(tenant_paths: tuple[Path, Path, Path]):
    _, _, tenants_path = tenant_paths

    router = TenantRouter(tenants_path)

    assert router.route_topic("events.raw", tenant_id="acme") == "acme.events.raw"


def test_query_engine_scopes_entity_reads_to_requested_schema(
    tenant_paths: tuple[Path, Path, Path],
):
    db_path, _, tenants_path = tenant_paths
    engine = QueryEngine(
        catalog=DataCatalog(),
        db_path=str(db_path),
        tenants_config_path=tenants_path,
    )

    acme_order = engine.get_entity("order", "ORD-SHARED", tenant_id="acme")
    demo_order = engine.get_entity("order", "ORD-SHARED", tenant_id="demo")

    assert acme_order is not None
    assert demo_order is not None
    assert acme_order["user_id"] == "USR-ACME"
    assert demo_order["user_id"] == "USR-DEMO"


def test_query_engine_scopes_metrics_to_requested_schema(
    tenant_paths: tuple[Path, Path, Path],
):
    db_path, _, tenants_path = tenant_paths
    engine = QueryEngine(
        catalog=DataCatalog(),
        db_path=str(db_path),
        tenants_config_path=tenants_path,
    )

    acme_metric = engine.get_metric("revenue", window="24h", tenant_id="acme")
    demo_metric = engine.get_metric("revenue", window="24h", tenant_id="demo")

    assert acme_metric["value"] == 205.5
    assert demo_metric["value"] == 40.0


def test_tenant_api_key_reads_only_own_schema(client: TestClient):
    response = client.get("/v1/entity/order/ORD-ACME", headers={"X-API-Key": "acme-key"})

    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == "USR-ACME-2"


def test_cross_tenant_entity_lookup_returns_404(client: TestClient):
    response = client.get("/v1/entity/order/ORD-ACME", headers={"X-API-Key": "demo-key"})

    assert response.status_code == 404
    assert response.json() == {"detail": "order/ORD-ACME not found"}


def test_metric_cache_does_not_leak_across_tenants(client: TestClient):
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

    client.app.state.query_cache = QueryCache(redis_client=FakeRedis())

    acme = client.get("/v1/metrics/revenue?window=24h", headers={"X-API-Key": "acme-key"})
    demo = client.get("/v1/metrics/revenue?window=24h", headers={"X-API-Key": "demo-key"})

    assert acme.status_code == 200
    assert acme.headers["X-Cache"] == "MISS"
    assert acme.json()["value"] == 205.5
    assert demo.status_code == 200
    assert demo.headers["X-Cache"] == "MISS"
    assert demo.json()["value"] == 40.0


def test_query_engine_falls_back_to_unqualified_tables_without_tenant_config(tmp_path: Path):
    db_path = tmp_path / "fallback.duckdb"
    engine = QueryEngine(
        catalog=DataCatalog(),
        db_path=str(db_path),
        tenants_config_path=tmp_path / "missing-tenants.yaml",
    )

    result = engine.get_entity("order", "ORD-20260404-1001")

    assert result is not None
    assert result["user_id"] == "USR-10001"


def test_open_metric_request_without_tenant_context_fails_closed_when_tenant_tables_exist(
    client: TestClient,
):
    # Empty in-memory keys; we want the request to reach the per-route
    # tenant-context check in sql_builder, so explicitly bypass the
    # middleware fail-closed (Codex audit p2_1 #5).
    manager = client.app.state.auth_manager
    manager.keys_by_value = {}
    manager._hashed_keys = []
    manager._loaded_keys = []
    manager._rate_windows.clear()
    client.app.state.auth_disabled = True

    response = client.get("/v1/metrics/revenue?window=24h")

    assert response.status_code == 503
    assert "Tenant context is required" in response.json()["detail"]


def test_metric_cache_does_not_bypass_fail_closed_without_tenant_context(
    client: TestClient,
):
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

    cache_key = QueryCache.metric_key("revenue", "24h")
    cached_payload = {
        "metric_name": "revenue",
        "value": 999.0,
        "unit": "USD",
        "window": "24h",
        "computed_at": "2026-04-11T00:00:00Z",
        "components": None,
        "meta": {
            "as_of": None,
            "is_historical": False,
            "freshness_seconds": None,
        },
    }
    fake_redis = FakeRedis()
    fake_redis.data[cache_key] = json.dumps(cached_payload)
    client.app.state.query_cache = QueryCache(redis_client=fake_redis)

    manager = client.app.state.auth_manager
    manager.keys_by_value = {}
    manager._hashed_keys = []
    manager._loaded_keys = []
    manager._rate_windows.clear()
    # See sibling fail-closed test: bypass middleware to reach sql_builder.
    client.app.state.auth_disabled = True

    response = client.get("/v1/metrics/revenue?window=24h")

    assert response.status_code == 503
    assert "Tenant context is required" in response.json()["detail"]


class _RecordingQueryEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def get_entity(
        self,
        entity_type: str,
        entity_id: str,
        tenant_id: str | None = None,
    ) -> dict:
        self.calls.append(("entity", tenant_id))
        return {
            "order_id": entity_id,
            "user_id": "USR-ACME",
            "_last_updated": "2026-04-11T00:00:00+00:00",
        }

    def get_metric(
        self,
        metric_name: str,
        window: str = "1h",
        as_of=None,
        tenant_id: str | None = None,
    ) -> dict:
        self.calls.append(("metric", tenant_id))
        return {"value": 1.0, "unit": "USD"}

    def execute_nl_query(
        self,
        question: str,
        context: dict | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        self.calls.append(("query", tenant_id))
        return {
            "data": [{"order_id": "ORD-1"}],
            "sql": "SELECT * FROM orders_v2 WHERE order_id = 'ORD-1'",
            "row_count": 1,
            "execution_time_ms": 1,
            "freshness_seconds": None,
        }


def test_agent_query_routes_pass_tenant_id_explicitly() -> None:
    engine = _RecordingQueryEngine()
    test_app = FastAPI()
    test_app.state.catalog = DataCatalog()
    test_app.state.query_engine = engine

    @test_app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        request.state.tenant_id = "acme"
        request.state.tenant_key = SimpleNamespace(tenant="acme")
        return await call_next(request)

    test_app.include_router(agent_router, prefix="/v1")

    with TestClient(test_app) as client:
        entity_response = client.get("/v1/entity/order/ORD-1")
        metric_response = client.get("/v1/metrics/revenue")
        query_response = client.post("/v1/query", json={"question": "show order ORD-1"})

    assert entity_response.status_code == 200
    assert metric_response.status_code == 200
    assert query_response.status_code == 200
    assert engine.calls == [
        ("entity", "acme"),
        ("metric", "acme"),
        ("query", "acme"),
    ]
