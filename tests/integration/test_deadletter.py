import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager
from src.serving.api.main import app

pytestmark = pytest.mark.integration

SCHEMA_EVENT_ID = "11111111-1111-1111-1111-111111111111"
SEMANTIC_EVENT_ID = "22222222-2222-2222-2222-222222222222"
DISMISSED_EVENT_ID = "33333333-3333-3333-3333-333333333333"
BETA_EVENT_ID = "44444444-4444-4444-4444-444444444444"


def _create_dead_letter_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dead_letter_events (
            event_id TEXT PRIMARY KEY,
            tenant_id TEXT DEFAULT 'default',
            event_type TEXT,
            payload JSON,
            failure_reason TEXT,
            failure_detail TEXT,
            received_at TIMESTAMP,
            retry_count INTEGER DEFAULT 0,
            last_retried_at TIMESTAMP,
            status TEXT DEFAULT 'failed'
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info('dead_letter_events')").fetchall()}
    if "tenant_id" not in columns:
        conn.execute("ALTER TABLE dead_letter_events ADD COLUMN tenant_id TEXT DEFAULT 'default'")


def _seed_dead_letter_events(conn) -> None:
    _create_dead_letter_table(conn)
    conn.execute("DELETE FROM dead_letter_events")
    conn.executemany(
        """
        INSERT INTO dead_letter_events (
            event_id,
            tenant_id,
            event_type,
            payload,
            failure_reason,
            failure_detail,
            received_at,
            retry_count,
            last_retried_at,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, NOW() - CAST(? AS INTERVAL), ?, ?, ?)
        """,
        [
            (
                SCHEMA_EVENT_ID,
                "acme",
                "unknown.type",
                json.dumps(
                    {
                        "event_id": SCHEMA_EVENT_ID,
                        "event_type": "unknown.type",
                        "timestamp": "2026-04-10T12:00:00+00:00",
                        "source": "deadletter-test",
                    }
                ),
                "schema_validation",
                "No schema for: unknown.type",
                "3 hours",
                0,
                None,
                "failed",
            ),
            (
                SEMANTIC_EVENT_ID,
                "acme",
                "order.created",
                json.dumps(
                    {
                        "event_id": SEMANTIC_EVENT_ID,
                        "event_type": "order.created",
                        "timestamp": "2026-04-10T13:00:00+00:00",
                        "source": "deadletter-test",
                        "order_id": "ORD-20260410-9001",
                        "user_id": "USR-42",
                        "status": "confirmed",
                        "items": [
                            {"product_id": "PROD-001", "quantity": 1, "unit_price": "79.99"},
                            {"product_id": "PROD-002", "quantity": 1, "unit_price": "20.00"},
                        ],
                        "total_amount": "10.00",
                        "currency": "USD",
                    }
                ),
                "semantic_validation",
                "Stated total 10.00 != computed 99.99",
                "2 hours",
                1,
                None,
                "failed",
            ),
            (
                DISMISSED_EVENT_ID,
                "acme",
                "order.created",
                json.dumps(
                    {
                        "event_id": DISMISSED_EVENT_ID,
                        "event_type": "order.created",
                        "timestamp": "2026-04-10T11:00:00+00:00",
                        "source": "deadletter-test",
                        "order_id": "ORD-20260410-9002",
                        "user_id": "USR-77",
                        "status": "confirmed",
                        "items": [
                            {"product_id": "PROD-003", "quantity": 1, "unit_price": "49.99"},
                        ],
                        "total_amount": "9.99",
                        "currency": "USD",
                    }
                ),
                "semantic_validation",
                "Stated total 9.99 != computed 49.99",
                "26 hours",
                0,
                None,
                "dismissed",
            ),
        ],
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "deadletter.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db_path))

    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        (
            "keys:\n"
            '  - key: "deadletter-readonly-key"\n'
            '    name: "Readonly Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 100\n"
            '    allowed_entity_types: ["order"]\n'
            '    created_at: "2026-04-10"\n'
            '  - key: "deadletter-ops-key"\n'
            '    name: "Ops Agent"\n'
            '    tenant: "acme"\n'
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-04-10"\n'
            '  - key: "deadletter-beta-ops-key"\n'
            '    name: "Beta Ops Agent"\n'
            '    tenant: "beta"\n'
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-04-10"\n'
        ),
        encoding="utf-8",
    )

    with TestClient(app) as c:
        manager = AuthManager(
            api_keys_path=api_keys_path,
            db_path=tmp_path / "usage.duckdb",
            admin_key="admin-secret",
        )
        manager.load()
        manager.ensure_usage_table()
        c.app.state.auth_manager = manager
        c.app.state.deadletter_produced_messages = []
        c.app.state.deadletter_producer = lambda topic, payload: (
            c.app.state.deadletter_produced_messages.append({"topic": topic, "payload": payload})
        )
        _seed_dead_letter_events(c.app.state.query_engine._conn)
        yield c


@pytest.fixture
def auth_headers():
    return {
        "readonly": {"X-API-Key": "deadletter-readonly-key"},
        "ops": {"X-API-Key": "deadletter-ops-key"},
        "beta_ops": {"X-API-Key": "deadletter-beta-ops-key"},
    }


def test_deadletter_requires_api_key(client: TestClient):
    response = client.get("/v1/deadletter")

    assert response.status_code == 401


def test_deadletter_list_returns_paginated_failed_events(client: TestClient, auth_headers):
    response = client.get(
        "/v1/deadletter?page=1&page_size=1",
        headers=auth_headers["ops"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total": 2,
        "pages": 2,
    }
    assert [item["event_id"] for item in body["items"]] == [SEMANTIC_EVENT_ID]
    assert body["items"][0]["failure_reason"] == "semantic_validation"
    assert "computed 99.99" in body["items"][0]["failure_detail"]


def test_deadletter_list_filters_by_reason(client: TestClient, auth_headers):
    response = client.get(
        "/v1/deadletter?reason=schema_validation",
        headers=auth_headers["readonly"],
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["event_id"] == SCHEMA_EVENT_ID
    assert items[0]["event_type"] == "unknown.type"
    assert items[0]["failure_reason"] == "schema_validation"
    assert items[0]["failure_detail"] == "No schema for: unknown.type"
    assert isinstance(items[0]["received_at"], str)
    assert items[0]["retry_count"] == 0
    assert items[0]["last_retried_at"] is None
    assert items[0]["status"] == "failed"


def test_deadletter_stats_returns_breakdown_for_active_failures(client: TestClient, auth_headers):
    response = client.get("/v1/deadletter/stats", headers=auth_headers["ops"])

    assert response.status_code == 200
    assert response.json()["counts"] == {
        "schema_validation": 1,
        "semantic_validation": 1,
    }
    assert response.json()["last_24h"] == 2


def test_deadletter_detail_returns_full_payload(client: TestClient, auth_headers):
    response = client.get(f"/v1/deadletter/{SEMANTIC_EVENT_ID}", headers=auth_headers["ops"])

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == SEMANTIC_EVENT_ID
    assert body["payload"]["order_id"] == "ORD-20260410-9001"
    assert body["failure_reason"] == "semantic_validation"


def test_deadletter_replay_resubmits_valid_corrected_payload(client: TestClient, auth_headers):
    response = client.post(
        f"/v1/deadletter/{SEMANTIC_EVENT_ID}/replay",
        headers=auth_headers["ops"],
        json={"corrected_payload": {"total_amount": "99.99"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == SEMANTIC_EVENT_ID
    assert body["status"] == "replayed"
    assert body["retry_count"] == 2
    assert len(client.app.state.deadletter_produced_messages) == 1
    produced = client.app.state.deadletter_produced_messages[0]
    assert produced["topic"] == "events.raw"
    assert produced["payload"]["event_id"] == SEMANTIC_EVENT_ID
    assert produced["payload"]["total_amount"] == "99.99"

    row = client.app.state.query_engine._conn.execute(
        """
        SELECT status, retry_count, last_retried_at, payload
        FROM dead_letter_events
        WHERE event_id = ?
        """,
        [SEMANTIC_EVENT_ID],
    ).fetchone()

    assert row[0] == "replayed"
    assert row[1] == 2
    assert row[2] is not None
    assert json.loads(row[3])["total_amount"] == "99.99"


def test_deadletter_replay_rejects_still_invalid_payload(client: TestClient, auth_headers):
    response = client.post(
        f"/v1/deadletter/{SCHEMA_EVENT_ID}/replay",
        headers=auth_headers["ops"],
    )

    assert response.status_code == 422
    assert "No schema for: unknown.type" in response.json()["detail"]
    assert client.app.state.deadletter_produced_messages == []

    row = client.app.state.query_engine._conn.execute(
        "SELECT status, retry_count FROM dead_letter_events WHERE event_id = ?",
        [SCHEMA_EVENT_ID],
    ).fetchone()
    assert row == ("failed", 0)


def test_deadletter_dismiss_marks_event_as_acknowledged(client: TestClient, auth_headers):
    response = client.post(
        f"/v1/deadletter/{SCHEMA_EVENT_ID}/dismiss",
        headers=auth_headers["ops"],
    )

    assert response.status_code == 200
    assert response.json() == {"event_id": SCHEMA_EVENT_ID, "status": "dismissed"}

    row = client.app.state.query_engine._conn.execute(
        "SELECT status FROM dead_letter_events WHERE event_id = ?",
        [SCHEMA_EVENT_ID],
    ).fetchone()
    assert row == ("dismissed",)


@pytest.mark.parametrize(
    "path",
    [
        f"/v1/deadletter/{SEMANTIC_EVENT_ID}/replay",
        f"/v1/deadletter/{SEMANTIC_EVENT_ID}/dismiss",
    ],
)
def test_deadletter_readonly_key_cannot_mutate(client: TestClient, auth_headers, path: str):
    response = client.post(path, headers=auth_headers["readonly"])

    assert response.status_code == 403


def test_deadletter_endpoints_are_tenant_scoped(client: TestClient, auth_headers):
    client.app.state.query_engine._conn.execute(
        """
        INSERT INTO dead_letter_events (
            event_id,
            tenant_id,
            event_type,
            payload,
            failure_reason,
            failure_detail,
            received_at,
            retry_count,
            last_retried_at,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, NOW() - INTERVAL '1 hour', ?, ?, ?)
        """,
        [
            BETA_EVENT_ID,
            "beta",
            "order.created",
            json.dumps(
                {
                    "event_id": BETA_EVENT_ID,
                    "event_type": "order.created",
                    "timestamp": "2026-04-10T13:00:00+00:00",
                    "source": "deadletter-test",
                    "order_id": "ORD-BETA",
                    "user_id": "USR-BETA",
                    "status": "confirmed",
                    "items": [{"product_id": "PROD-001", "quantity": 1, "unit_price": "79.99"}],
                    "total_amount": "10.00",
                    "currency": "USD",
                }
            ),
            "semantic_validation",
            "beta failure",
            0,
            None,
            "failed",
        ],
    )

    acme_list = client.get("/v1/deadletter", headers=auth_headers["ops"])
    beta_list = client.get("/v1/deadletter", headers=auth_headers["beta_ops"])
    acme_detail = client.get(f"/v1/deadletter/{BETA_EVENT_ID}", headers=auth_headers["ops"])
    acme_replay = client.post(
        f"/v1/deadletter/{BETA_EVENT_ID}/replay",
        headers=auth_headers["ops"],
    )
    acme_dismiss = client.post(
        f"/v1/deadletter/{BETA_EVENT_ID}/dismiss",
        headers=auth_headers["ops"],
    )

    assert acme_list.status_code == 200
    assert BETA_EVENT_ID not in [item["event_id"] for item in acme_list.json()["items"]]
    assert beta_list.status_code == 200
    assert [item["event_id"] for item in beta_list.json()["items"]] == [BETA_EVENT_ID]
    assert acme_detail.status_code == 404
    assert acme_replay.status_code == 404
    assert acme_dismiss.status_code == 404
