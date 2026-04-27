import gc
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from src.serving.api import analytics as analytics_module
from src.serving.api.auth import AuthManager
from src.serving.api.main import app
from src.serving.semantic_layer.query_engine import QueryEngine

pytestmark = pytest.mark.integration


def _write_api_keys(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "keys:\n"
            '  - key: "analytics-acme-key"\n'
            '    name: "Acme Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-04-10"\n'
            '  - key: "analytics-globex-key"\n'
            '    name: "Globex Agent"\n'
            '    tenant: "globex"\n'
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-04-10"\n'
        ),
        encoding="utf-8",
    )


def _wait_until(assertion, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            assertion()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error


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
        yield c


def test_analytics_endpoints_require_admin_key(client: TestClient):
    response = client.get(
        "/v1/admin/analytics/usage",
        headers={"X-API-Key": "analytics-acme-key"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing admin key."}


def test_analytics_usage_logs_requests_and_supports_tenant_filter(client: TestClient):
    client.get(
        "/v1/entity/order/ORD-20260404-1001",
        headers={"X-API-Key": "analytics-acme-key"},
    )
    client.get(
        "/v1/metrics/revenue",
        headers={"X-API-Key": "analytics-globex-key"},
    )

    def assert_rows_logged():
        rows = (
            duckdb.connect(str(client.app.state.auth_manager.db_path))
            .execute("SELECT tenant, endpoint FROM api_sessions ORDER BY tenant, endpoint")
            .fetchall()
        )
        assert rows == [
            ("acme", "/v1/entity/order"),
            ("globex", "/v1/metrics/revenue"),
        ]

    _wait_until(assert_rows_logged)

    response = client.get(
        "/v1/admin/analytics/usage?window=24h&tenant=acme",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["window"] == "24h"
    assert payload["tenants"][0]["tenant"] == "acme"
    assert payload["tenants"][0]["total_requests"] == 1
    assert payload["tenants"][0]["error_rate"] == 0.0
    assert payload["tenants"][0]["cache_hit_rate"] == 0.0
    assert payload["tenants"][0]["top_endpoints"] == ["/v1/entity/order"]
    assert payload["tenants"][0]["avg_duration_ms"] >= 0


def test_analytics_latency_returns_percentiles_per_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    original_get_metric = QueryEngine.get_metric

    def delayed_get_metric(self, metric_name: str, window: str = "1h", as_of=None):
        time.sleep(0.02)
        return original_get_metric(self, metric_name, window=window, as_of=as_of)

    monkeypatch.setattr(QueryEngine, "get_metric", delayed_get_metric)

    for _ in range(3):
        response = client.get(
            "/v1/metrics/revenue",
            headers={"X-API-Key": "analytics-acme-key"},
        )
        assert response.status_code == 200

    def assert_logged():
        count = (
            duckdb.connect(str(client.app.state.auth_manager.db_path))
            .execute("SELECT COUNT(*) FROM api_sessions WHERE endpoint = '/v1/metrics/revenue'")
            .fetchone()[0]
        )
        assert count == 3

    _wait_until(assert_logged)

    response = client.get(
        "/v1/admin/analytics/latency",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert response.status_code == 200
    assert response.json()["window"] == "24h"
    metric_row = next(
        item for item in response.json()["endpoints"] if item["endpoint"] == "/v1/metrics/revenue"
    )
    assert metric_row["requests"] == 3
    assert metric_row["p50_ms"] > 0
    assert metric_row["p95_ms"] >= metric_row["p50_ms"]
    assert metric_row["p99_ms"] >= metric_row["p95_ms"]


def test_analytics_top_queries_and_entities_return_ranked_results(client: TestClient):
    for question in ["revenue today", "revenue today", "top 2 products today"]:
        response = client.post(
            "/v1/query",
            headers={"X-API-Key": "analytics-acme-key"},
            json={"question": question},
        )
        assert response.status_code == 200

    for entity_id in ["ORD-20260404-1001", "ORD-20260404-1001", "ORD-20260404-1002"]:
        response = client.get(
            f"/v1/entity/order/{entity_id}",
            headers={"X-API-Key": "analytics-acme-key"},
        )
        assert response.status_code == 200

    def assert_query_logs():
        count = (
            duckdb.connect(str(client.app.state.auth_manager.db_path))
            .execute("SELECT COUNT(*) FROM api_sessions WHERE tenant = 'acme'")
            .fetchone()[0]
        )
        assert count >= 6

    _wait_until(assert_query_logs)

    top_queries = client.get(
        "/v1/admin/analytics/top-queries?limit=2",
        headers={"X-Admin-Key": "admin-secret"},
    )
    top_entities = client.get(
        "/v1/admin/analytics/top-entities?limit=2",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert top_queries.status_code == 200
    assert top_queries.json()["queries"][0] == {
        "query": "revenue today",
        "count": 2,
    }
    assert top_entities.status_code == 200
    assert top_entities.json()["entities"][0] == {
        "entity_type": "order",
        "entity_id": "ORD-20260404-1001",
        "count": 2,
    }


def test_analytics_logging_is_non_blocking(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    original_schedule_session_write = analytics_module._schedule_session_write
    monkeypatch.setattr(
        analytics_module,
        "_schedule_session_write",
        lambda *args, **kwargs: None,
    )
    baseline_started_at = time.perf_counter()
    warm_response = client.get(
        "/v1/catalog",
        headers={"X-API-Key": "analytics-acme-key"},
    )
    baseline_elapsed = time.perf_counter() - baseline_started_at
    assert warm_response.status_code == 200
    monkeypatch.setattr(
        analytics_module,
        "_schedule_session_write",
        original_schedule_session_write,
    )

    original_insert_session = analytics_module._insert_session

    def delayed_insert_session(*args, **kwargs):
        time.sleep(0.25)
        original_insert_session(*args, **kwargs)

    monkeypatch.setattr(analytics_module, "_insert_session", delayed_insert_session)

    started_at = time.perf_counter()
    response = client.get(
        "/v1/catalog",
        headers={"X-API-Key": "analytics-acme-key"},
    )
    elapsed = time.perf_counter() - started_at

    assert response.status_code == 200
    assert elapsed < max(0.2, baseline_elapsed + 0.15)

    def assert_logged():
        count = (
            duckdb.connect(str(client.app.state.auth_manager.db_path))
            .execute("SELECT COUNT(*) FROM api_sessions WHERE endpoint = '/v1/catalog'")
            .fetchone()[0]
        )
        assert count == 1

    _wait_until(assert_logged)


def test_analytics_background_logging_survives_forced_gc(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    original_insert_session = analytics_module._insert_session

    def delayed_insert_session(*args, **kwargs):
        time.sleep(0.3)
        original_insert_session(*args, **kwargs)

    monkeypatch.setattr(analytics_module, "_insert_session", delayed_insert_session)

    for _ in range(5):
        response = client.get(
            "/v1/metrics/revenue",
            headers={"X-API-Key": "analytics-acme-key"},
        )
        assert response.status_code == 200
        gc.collect()
        time.sleep(0.05)

    def assert_logged():
        count = (
            duckdb.connect(str(client.app.state.auth_manager.db_path))
            .execute("SELECT COUNT(*) FROM api_sessions WHERE endpoint = '/v1/metrics/revenue'")
            .fetchone()[0]
        )
        assert count == 5

    _wait_until(assert_logged, timeout=5.0)


def test_analytics_anomalies_flags_tenants_with_hourly_spikes(client: TestClient):
    db_path = client.app.state.auth_manager.db_path
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_sessions (
                request_id TEXT PRIMARY KEY,
                tenant TEXT,
                key_name TEXT,
                endpoint TEXT,
                method TEXT,
                status_code INTEGER,
                duration_ms FLOAT,
                cache_hit BOOLEAN,
                entity_type TEXT,
                entity_id TEXT,
                metric_name TEXT,
                query_engine TEXT,
                query_text TEXT,
                ts TIMESTAMP DEFAULT NOW()
            )
            """
        )
        conn.execute("DELETE FROM api_sessions")
        rows = []
        for hour in range(1, 5):
            rows.append(
                (
                    f"hist-{hour}",
                    "globex",
                    "Globex Agent",
                    "/v1/query",
                    "POST",
                    200,
                    12.0,
                    False,
                    None,
                    None,
                    None,
                    "rule_based",
                    "historical",
                    now - timedelta(hours=hour),
                )
            )
        for index in range(12):
            rows.append(
                (
                    f"spike-{index}",
                    "globex",
                    "Globex Agent",
                    "/v1/query",
                    "POST",
                    200,
                    15.0,
                    False,
                    None,
                    None,
                    None,
                    "rule_based",
                    "spike",
                    now + timedelta(minutes=5),
                )
            )
        conn.executemany(
            """
            INSERT INTO api_sessions (
                request_id,
                tenant,
                key_name,
                endpoint,
                method,
                status_code,
                duration_ms,
                cache_hit,
                entity_type,
                entity_id,
                metric_name,
                query_engine,
                query_text,
                ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    finally:
        conn.close()

    response = client.get(
        "/v1/admin/analytics/anomalies",
        headers={"X-Admin-Key": "admin-secret"},
    )

    assert response.status_code == 200
    assert response.json()["anomalies"] == [
        {
            "tenant": "globex",
            "current_hour_requests": 12,
            "hourly_average": 1.0,
            "spike_ratio": 12.0,
        }
    ]
