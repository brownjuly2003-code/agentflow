import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _disable_auth(client: TestClient) -> None:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {}
    manager._rate_windows.clear()


def _prepare_time_travel_data(client: TestClient) -> None:
    conn = client.app.state.query_engine._conn
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()
    }

    if "entity_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN entity_id VARCHAR")
    if "event_type" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN event_type VARCHAR")
    if "entity_type" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN entity_type VARCHAR")
    if "entity_data" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN entity_data VARCHAR")

    conn.execute("DELETE FROM pipeline_events")
    conn.execute("DELETE FROM orders_v2")

    conn.executemany(
        """
        INSERT INTO orders_v2 (
            order_id, user_id, status, total_amount, currency, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "ORD-TT-1",
                "USR-TT-1",
                "shipped",
                100.0,
                "USD",
                datetime(2026, 4, 9, 10, 0, tzinfo=UTC),
            ),
            (
                "ORD-TT-2",
                "USR-TT-2",
                "confirmed",
                50.0,
                "USD",
                datetime(2026, 4, 9, 11, 15, tzinfo=UTC),
            ),
            (
                "ORD-TT-3",
                "USR-TT-3",
                "cancelled",
                25.0,
                "USD",
                datetime(2026, 4, 9, 11, 45, tzinfo=UTC),
            ),
            (
                "ORD-TT-4",
                "USR-TT-4",
                "delivered",
                70.0,
                "USD",
                datetime(2026, 4, 9, 12, 30, tzinfo=UTC),
            ),
        ],
    )

    conn.executemany(
        """
        INSERT INTO pipeline_events (
            event_id, topic, event_type, processed_at, entity_id, entity_type, entity_data
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "evt-tt-1",
                "events.validated",
                "order.created",
                datetime(2026, 4, 9, 10, 0, tzinfo=UTC),
                "ORD-TT-1",
                "order",
                json.dumps(
                    {
                        "order_id": "ORD-TT-1",
                        "user_id": "USR-TT-1",
                        "status": "pending",
                        "total_amount": 100.0,
                        "currency": "USD",
                        "created_at": "2026-04-09T10:00:00Z",
                    }
                ),
            ),
            (
                "evt-tt-2",
                "events.validated",
                "order.confirmed",
                datetime(2026, 4, 9, 12, 0, tzinfo=UTC),
                "ORD-TT-1",
                "order",
                json.dumps(
                    {
                        "order_id": "ORD-TT-1",
                        "user_id": "USR-TT-1",
                        "status": "confirmed",
                        "total_amount": 100.0,
                        "currency": "USD",
                        "created_at": "2026-04-09T10:00:00Z",
                    }
                ),
            ),
            (
                "evt-tt-3",
                "events.validated",
                "order.shipped",
                datetime(2026, 4, 9, 14, 0, tzinfo=UTC),
                "ORD-TT-1",
                "order",
                json.dumps(
                    {
                        "order_id": "ORD-TT-1",
                        "user_id": "USR-TT-1",
                        "status": "shipped",
                        "total_amount": 100.0,
                        "currency": "USD",
                        "created_at": "2026-04-09T10:00:00Z",
                    }
                ),
            ),
        ],
    )


class TestTimeTravelQueries:
    def test_entity_as_of_returns_historical_snapshot(self, client):
        _disable_auth(client)
        _prepare_time_travel_data(client)

        response = client.get(
            "/v1/entity/order/ORD-TT-1?as_of=2026-04-09T11:00:00Z"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["status"] == "pending"
        assert data["meta"]["as_of"] == "2026-04-09T11:00:00Z"
        assert data["meta"]["is_historical"] is True
        assert data["meta"]["freshness_seconds"] is None

    def test_entity_as_of_uses_latest_snapshot_before_anchor(self, client):
        _disable_auth(client)
        _prepare_time_travel_data(client)

        response = client.get(
            "/v1/entity/order/ORD-TT-1?as_of=2026-04-09T13:00:00Z"
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "confirmed"

    def test_entity_as_of_before_first_event_returns_404(self, client):
        _disable_auth(client)
        _prepare_time_travel_data(client)

        response = client.get(
            "/v1/entity/order/ORD-TT-1?as_of=2026-04-09T09:00:00Z"
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "order/ORD-TT-1 not found"

    def test_metric_as_of_anchors_window_end(self, client):
        _disable_auth(client)
        _prepare_time_travel_data(client)

        response = client.get(
            "/v1/metrics/revenue?window=1h&as_of=2026-04-09T12:00:00Z"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["value"] == 50.0
        assert data["meta"]["is_historical"] is True
        assert data["meta"]["as_of"] == "2026-04-09T12:00:00Z"

    def test_metric_as_of_shifts_window(self, client):
        _disable_auth(client)
        _prepare_time_travel_data(client)

        response = client.get(
            "/v1/metrics/revenue?window=1h&as_of=2026-04-09T13:00:00Z"
        )

        assert response.status_code == 200
        assert response.json()["value"] == 70.0

    def test_entity_as_of_in_future_returns_422(self, client):
        _disable_auth(client)
        _prepare_time_travel_data(client)
        future_as_of = (datetime.now(UTC) + timedelta(minutes=5)).isoformat().replace(
            "+00:00", "Z"
        )

        response = client.get(f"/v1/entity/order/ORD-TT-1?as_of={future_as_of}")

        assert response.status_code == 422
        assert "future" in response.json()["detail"]

    def test_metric_without_as_of_reports_non_historical_meta(self, client):
        _disable_auth(client)
        _prepare_time_travel_data(client)

        response = client.get("/v1/metrics/revenue?window=1h")

        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["as_of"] is None
        assert data["meta"]["is_historical"] is False
