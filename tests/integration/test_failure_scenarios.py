from datetime import datetime, timedelta

import duckdb
import pytest
from fastapi.testclient import TestClient

from src.processing.local_pipeline import _ensure_tables, _process_event
from src.quality.monitors.metrics_collector import HealthCollector, HealthStatus
from src.serving.api.auth import AuthManager
from src.serving.api.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client, tmp_path):
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        (
            "keys:\n"
            '  - key: "tenant-order-key"\n'
            '    name: "Order Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 2\n"
            '    allowed_entity_types: ["order"]\n'
            '    created_at: "2026-04-10"\n'
            '  - key: "tenant-ops-key"\n'
            '    name: "Ops Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 10\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-04-10"\n'
        ),
        encoding="utf-8",
    )

    manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=tmp_path / "usage.duckdb",
        admin_key="admin-secret",
    )
    manager.load()
    manager.ensure_usage_table()
    client.app.state.auth_manager = manager

    return {
        "order": {"X-API-Key": "tenant-order-key"},
        "ops": {"X-API-Key": "tenant-ops-key"},
    }


class TestAuthFailures:
    def test_missing_api_key_returns_401(self, client, auth_headers):
        response = client.get("/v1/metrics/revenue")

        assert response.status_code == 401
        assert "X-API-Key" in response.json()["detail"]

    def test_invalid_api_key_returns_401(self, client, auth_headers):
        response = client.get(
            "/v1/metrics/revenue",
            headers={"X-API-Key": "bad-key"},
        )

        assert response.status_code == 401
        assert "Invalid or missing API key" in response.json()["detail"]

    def test_rate_limit_triggers_429(self, client, auth_headers):
        first = client.get("/v1/metrics/revenue", headers=auth_headers["order"])
        second = client.get("/v1/metrics/revenue", headers=auth_headers["order"])
        third = client.get("/v1/metrics/revenue", headers=auth_headers["order"])

        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 429
        assert third.headers["Retry-After"] == "60"
        assert "2 requests/minute" in third.json()["detail"]

    def test_forbidden_entity_type_returns_403(self, client, auth_headers):
        response = client.get(
            "/v1/entity/user/USR-10001",
            headers=auth_headers["order"],
        )

        assert response.status_code == 403
        assert "cannot access entity type 'user'" in response.json()["detail"]


class TestEntityNotFound:
    def test_unknown_order_id_returns_404(self, client, auth_headers):
        response = client.get(
            "/v1/entity/order/ORD-404-NOT-FOUND",
            headers=auth_headers["ops"],
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "order/ORD-404-NOT-FOUND not found"

    def test_unknown_user_id_returns_404_not_500(self, client, auth_headers):
        response = client.get(
            "/v1/entity/user/USR-404-NOT-FOUND",
            headers=auth_headers["ops"],
        )

        assert response.status_code == 404
        assert "Internal Server Error" not in response.text

    def test_404_body_has_entity_type_and_id(self, client, auth_headers):
        response = client.get(
            "/v1/entity/order/ORD-404-DETAIL",
            headers=auth_headers["ops"],
        )
        detail = response.json()["detail"]

        assert response.status_code == 404
        assert "order" in detail
        assert "ORD-404-DETAIL" in detail

    def test_unknown_entity_type_returns_404(self, client, auth_headers):
        response = client.get(
            "/v1/entity/spaceship/USS-Enterprise",
            headers=auth_headers["ops"],
        )

        assert response.status_code == 404
        assert "Unknown entity type: spaceship" in response.json()["detail"]


class TestInvalidQueries:
    def test_nl_query_with_injection_attempt_is_safe(self, client, auth_headers):
        response = client.post(
            "/v1/query",
            headers=auth_headers["ops"],
            json={"question": "What is revenue today'; DROP TABLE orders_v2; --"},
        )
        follow_up = client.get(
            "/v1/metrics/revenue?window=24h",
            headers=auth_headers["ops"],
        )

        assert response.status_code == 200
        assert follow_up.status_code == 200
        assert "DROP TABLE" not in response.text.upper()
        assert response.json()["sql"].startswith("SELECT SUM(total_amount)")

    def test_metric_unknown_name_returns_404(self, client, auth_headers):
        response = client.get(
            "/v1/metrics/nonexistent",
            headers=auth_headers["ops"],
        )

        assert response.status_code == 404
        assert "Unknown metric: nonexistent" in response.json()["detail"]

    def test_nl_query_too_short_returns_422(self, client, auth_headers):
        response = client.post(
            "/v1/query",
            headers=auth_headers["ops"],
            json={"question": "hi"},
        )

        assert response.status_code == 422

    def test_nl_query_missing_question_returns_422(self, client, auth_headers):
        response = client.post(
            "/v1/query",
            headers=auth_headers["ops"],
            json={},
        )

        assert response.status_code == 422


class TestDataQuality:
    def test_invalid_event_goes_to_deadletter(self, tmp_path, sample_invalid_event):
        db_path = tmp_path / "pipeline.duckdb"
        conn = duckdb.connect(str(db_path))
        try:
            _ensure_tables(conn)
            success, reason = _process_event(conn, sample_invalid_event)
            row = conn.execute(
                "SELECT topic FROM pipeline_events WHERE event_id = ?",
                [sample_invalid_event["event_id"]],
            ).fetchone()
        finally:
            conn.close()

        assert success is False
        assert reason.startswith("schema:")
        assert row == ("events.deadletter",)

    def test_deadletter_record_keeps_invalid_event_type(self, tmp_path, sample_invalid_event):
        db_path = tmp_path / "pipeline.duckdb"
        conn = duckdb.connect(str(db_path))
        try:
            _ensure_tables(conn)
            _process_event(conn, sample_invalid_event)
            row = conn.execute(
                "SELECT event_type FROM pipeline_events WHERE event_id = ?",
                [sample_invalid_event["event_id"]],
            ).fetchone()
        finally:
            conn.close()

        assert row == ("unknown.type",)

    def test_health_shows_degraded_when_no_recent_events(self, tmp_path, monkeypatch):
        db_path = tmp_path / "health.duckdb"
        conn = duckdb.connect(str(db_path))
        try:
            conn.execute(
                "CREATE TABLE pipeline_events ("
                "event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)"
            )
        finally:
            conn.close()

        monkeypatch.setenv("DUCKDB_PATH", str(db_path))

        collector = HealthCollector()
        collector._checks = [collector._check_freshness]
        health = collector.collect()

        assert health.overall == HealthStatus.DEGRADED
        assert health.components[0].status == HealthStatus.DEGRADED
        assert health.components[0].metrics["last_event_age_seconds"] is None

    def test_health_freshness_propagates_unexpected_errors(self, monkeypatch):
        def raise_unexpected(*args, **kwargs):
            raise RuntimeError("unexpected freshness failure")

        monkeypatch.setattr(duckdb, "connect", raise_unexpected)

        with pytest.raises(RuntimeError, match="unexpected freshness failure"):
            HealthCollector()._check_freshness()

    def test_quality_score_counts_deadletters(self, tmp_path, monkeypatch):
        db_path = tmp_path / "quality.duckdb"
        conn = duckdb.connect(str(db_path))
        now = datetime.now().replace(microsecond=0)
        recent = [now - timedelta(minutes=index) for index in range(10)]
        try:
            conn.execute(
                "CREATE TABLE pipeline_events ("
                "event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)"
            )
            conn.executemany(
                "INSERT INTO pipeline_events VALUES (?, ?, ?)",
                [
                    (
                        f"evt-{index}",
                        "events.deadletter" if index < 2 else "events.validated",
                        recent[index],
                    )
                    for index in range(10)
                ],
            )
        finally:
            conn.close()

        monkeypatch.setenv("DUCKDB_PATH", str(db_path))

        quality = HealthCollector()._check_quality_score()

        assert quality.status == HealthStatus.UNHEALTHY
        assert quality.metrics["rejected_events"] == 2
        assert quality.metrics["total_events"] == 10
        assert quality.metrics["pass_rate"] == 0.8

    def test_quality_score_propagates_unexpected_errors(self, monkeypatch):
        def raise_unexpected(*args, **kwargs):
            raise RuntimeError("unexpected quality failure")

        monkeypatch.setattr(duckdb, "connect", raise_unexpected)

        with pytest.raises(RuntimeError, match="unexpected quality failure"):
            HealthCollector()._check_quality_score()

    def test_health_collect_propagates_unexpected_check_errors(self):
        collector = HealthCollector()

        def unexpected_check():
            raise RuntimeError("check exploded")

        collector._checks = [unexpected_check]

        with pytest.raises(RuntimeError, match="check exploded"):
            collector.collect()
