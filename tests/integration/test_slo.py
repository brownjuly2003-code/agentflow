from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager
from src.serving.api.main import app

pytestmark = pytest.mark.integration


def _write_slo_config(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_pipeline_events(
    client: TestClient,
    *,
    rows: list[tuple[str, str, str, int | None, int | None]],
    include_status_code: bool = True,
) -> None:
    conn = client.app.state.query_engine._conn
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()
    }
    if "latency_ms" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN latency_ms INTEGER")
    if include_status_code and "status_code" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN status_code INTEGER")

    conn.execute("DELETE FROM pipeline_events")

    insert_columns = ["event_id", "topic", "processed_at", "latency_ms"]
    values_sql = "?, ?, NOW() - CAST(? AS INTERVAL), ?"
    if include_status_code:
        insert_columns.append("status_code")
        values_sql = f"{values_sql}, ?"

    conn.executemany(
        (
            f"INSERT INTO pipeline_events ({', '.join(insert_columns)}) "
            f"VALUES ({values_sql})"
        ),
        rows,
    )


@pytest.fixture
def client(tmp_path: Path):
    slo_path = tmp_path / "config" / "slo.yaml"
    _write_slo_config(
        slo_path,
        (
            "slos:\n"
            "  - name: api_latency_p95\n"
            "    description: \"95th percentile API latency < 100ms for entity queries\"\n"
            "    target: 0.99\n"
            "    measurement: p95_latency_ms\n"
            "    threshold: 100\n"
            "    window_days: 30\n"
            "  - name: data_freshness\n"
            "    description: \"Pipeline data freshness < 30 seconds\"\n"
            "    target: 0.999\n"
            "    measurement: freshness_seconds\n"
            "    threshold: 30\n"
            "    window_days: 7\n"
            "  - name: error_rate\n"
            "    description: \"API error rate (5xx) < 0.1%\"\n"
            "    target: 0.999\n"
            "    measurement: error_rate_percent\n"
            "    threshold: 0.1\n"
            "    window_days: 30\n"
        ),
    )

    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        (
            "keys:\n"
            "  - key: \"slo-test-key\"\n"
            "    name: \"SLO Agent\"\n"
            "    tenant: \"acme\"\n"
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            "    created_at: \"2026-04-10\"\n"
        ),
        encoding="utf-8",
    )

    previous_slo_path = getattr(app.state, "slo_config_path", None)
    app.state.slo_config_path = slo_path

    with TestClient(app) as c:
        manager = AuthManager(
            api_keys_path=api_keys_path,
            db_path=tmp_path / "usage.duckdb",
        )
        manager.load()
        manager.ensure_usage_table()
        c.app.state.auth_manager = manager
        yield c

    app.state.slo_config_path = previous_slo_path


def test_slo_requires_api_key(client: TestClient):
    response = client.get("/v1/slo")

    assert response.status_code == 401


def test_slo_returns_statuses_and_error_budget(client: TestClient):
    _seed_pipeline_events(
        client,
        rows=[
            ("evt-1", "events.validated", "5 seconds", 101, 200),
            ("evt-2", "events.validated", "5 seconds", 101, 200),
            ("evt-3", "events.validated", "5 seconds", 101, 200),
            ("evt-4", "events.validated", "5 seconds", 101, 200),
            ("evt-5", "events.validated", "5 seconds", 101, 200),
            ("evt-6", "events.validated", "5 seconds", 101, 200),
            ("evt-7", "events.validated", "5 seconds", 101, 200),
            ("evt-8", "events.validated", "5 seconds", 101, 200),
            ("evt-9", "events.validated", "5 seconds", 101, 500),
            ("evt-10", "events.validated", "5 seconds", 101, 502),
        ],
    )

    response = client.get("/v1/slo", headers={"X-API-Key": "slo-test-key"})

    assert response.status_code == 200
    data = {item["name"]: item for item in response.json()["slos"]}
    assert set(data) == {"api_latency_p95", "data_freshness", "error_rate"}
    assert data["api_latency_p95"]["status"] == "at_risk"
    assert 0 < data["api_latency_p95"]["error_budget_remaining"] < 0.2
    assert data["data_freshness"]["status"] == "healthy"
    assert data["data_freshness"]["current"] == 1.0
    assert data["error_rate"]["status"] == "breached"
    assert data["error_rate"]["current"] == 0.8


def test_slo_uses_yaml_as_single_source_of_truth(client: TestClient):
    _write_slo_config(
        client.app.state.slo_config_path,
        (
            "slos:\n"
            "  - name: custom_latency_budget\n"
            "    description: \"Custom latency budget\"\n"
            "    target: 0.95\n"
            "    measurement: p95_latency_ms\n"
            "    threshold: 250\n"
            "    window_days: 14\n"
        ),
    )
    _seed_pipeline_events(
        client,
        rows=[
            ("evt-custom-1", "events.validated", "10 seconds", 200, 200),
            ("evt-custom-2", "events.validated", "10 seconds", 220, 200),
        ],
    )

    response = client.get("/v1/slo", headers={"X-API-Key": "slo-test-key"})

    assert response.status_code == 200
    assert response.json() == {
        "slos": [
            {
                "name": "custom_latency_budget",
                "target": 0.95,
                "current": 1.0,
                "error_budget_remaining": 1.0,
                "status": "healthy",
                "window_days": 14,
            }
        ]
    }


def test_slo_uses_deadletter_ratio_when_status_codes_are_absent(client: TestClient):
    _write_slo_config(
        client.app.state.slo_config_path,
        (
            "slos:\n"
            "  - name: error_rate\n"
            "    description: \"API error rate (5xx) < 0.1%\"\n"
            "    target: 0.999\n"
            "    measurement: error_rate_percent\n"
            "    threshold: 0.1\n"
            "    window_days: 30\n"
        ),
    )
    _seed_pipeline_events(
        client,
        rows=[
            ("evt-1", "events.validated", "15 seconds", 80),
            ("evt-2", "events.validated", "15 seconds", 80),
            ("evt-3", "events.validated", "15 seconds", 80),
            ("evt-4", "events.validated", "15 seconds", 80),
            ("evt-5", "events.validated", "15 seconds", 80),
            ("evt-6", "events.validated", "15 seconds", 80),
            ("evt-7", "events.validated", "15 seconds", 80),
            ("evt-8", "events.validated", "15 seconds", 80),
            ("evt-9", "events.deadletter", "15 seconds", 80),
            ("evt-10", "events.deadletter", "15 seconds", 80),
        ],
        include_status_code=False,
    )

    response = client.get("/v1/slo", headers={"X-API-Key": "slo-test-key"})

    assert response.status_code == 200
    assert response.json()["slos"] == [
        {
            "name": "error_rate",
            "target": 0.999,
            "current": 0.8,
            "error_budget_remaining": 0.0,
            "status": "breached",
            "window_days": 30,
        }
    ]
