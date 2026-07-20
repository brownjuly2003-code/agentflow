"""Integration tests for the exception inbox —
GET/POST /v1/ops/exceptions* (ops-surfaces-spec.md §4, D4). Exercises the
demo story pin (I7: the two seeded dead-letter rows make a non-empty inbox),
native dead-letter lifecycle mirroring with no overlay row (I6), stable item
ids (I5), the R1/R2 reconciliation checks, idempotent concurrent reads (I10),
and the manual_resolutions/last_24h re-pin by arithmetic (I9). Tenant scoping
(I8) and the no-third-path ratchet (I1) live in test_tenant_isolation.py and
test_control_plane_store.py respectively — same pattern as the other ops
surfaces.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager
from src.serving.api.main import app

pytestmark = pytest.mark.integration

_PII_FIELD_NAMES = ("first_name", "last_name", "email", "phone", "birth_date")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "exceptions-inbox.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db_path))
    monkeypatch.setenv("SERVING_BACKEND", "duckdb")
    monkeypatch.setenv("AGENTFLOW_AUTH_DISABLED", "true")

    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "exceptions-inbox-authed.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db_path))
    monkeypatch.setenv("SERVING_BACKEND", "duckdb")

    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        (
            "keys:\n"
            '  - key: "exceptions-readonly-key"\n'
            '    name: "Readonly Agent"\n'
            '    tenant: "default"\n'
            "    rate_limit_rpm: 100\n"
            '    allowed_entity_types: ["order"]\n'
            '    created_at: "2026-07-04"\n'
            '  - key: "exceptions-ops-key"\n'
            '    name: "Ops Agent"\n'
            '    tenant: "default"\n'
            "    rate_limit_rpm: 100\n"
            "    allowed_entity_types: null\n"
            '    created_at: "2026-07-04"\n'
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
        yield c


@pytest.fixture
def auth_headers():
    return {
        "readonly": {"X-API-Key": "exceptions-readonly-key"},
        "ops": {"X-API-Key": "exceptions-ops-key"},
    }


# --- demo story (I7) / stats re-pin (I9) ------------------------------------


def test_default_view_is_non_empty_with_the_seeded_deadletter_items(client: TestClient):
    response = client.get("/v1/ops/exceptions")

    assert response.status_code == 200
    data = response.json()
    item_ids = {item["item_id"] for item in data["items"]}

    assert item_ids == {"dl:evt-004", "dl:evt-009"}
    for item in data["items"]:
        assert item["source"] == "deadletter"
        assert item["severity"] == "high"
        assert item["status"] == "open"
        assert {action["action"] for action in item["actions"]} == {"replay", "dismiss"}


def test_stats_reflect_the_demo_seed(client: TestClient):
    response = client.get("/v1/ops/exceptions/stats")

    assert response.status_code == 200
    data = response.json()

    assert data["by_source"] == {"deadletter": {"open": 2}}
    assert data["last_24h"] == 2
    assert data["manual_resolutions"] == 0


def test_no_pii_field_names_leak_into_the_inbox(client: TestClient):
    response = client.get("/v1/ops/exceptions")

    assert response.status_code == 200
    for field_name in _PII_FIELD_NAMES:
        assert field_name not in response.text


def test_source_filter_narrows_to_deadletter(client: TestClient):
    response = client.get("/v1/ops/exceptions", params={"source": "webhook_delivery"})

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_pagination_shape(client: TestClient):
    response = client.get("/v1/ops/exceptions", params={"page": 1, "page_size": 1})

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["pagination"] == {"page": 1, "page_size": 1, "total": 2, "pages": 2}


# --- I5: stable item ids -----------------------------------------------------


def test_item_ids_are_stable_across_calls(client: TestClient):
    first = client.get("/v1/ops/exceptions").json()
    second = client.get("/v1/ops/exceptions").json()

    first_ids = sorted(item["item_id"] for item in first["items"])
    second_ids = sorted(item["item_id"] for item in second["items"])
    assert first_ids == second_ids == ["dl:evt-004", "dl:evt-009"]


# --- reconciliation: R1 journal_vs_store / R2 stuck_replay -------------------


def test_r1_detects_a_serving_projection_behind_its_journal_stage(client: TestClient):
    conn = client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO pipeline_events
            (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at)
        VALUES ('evt-r1-test', 'orders.status', 'default', 'ORD-20260404-1003',
                'order.status.shipped', NULL, NOW())
        """
    )

    response = client.get("/v1/ops/exceptions", params={"source": "reconciliation"})

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["item_id"] for item in items] == ["rc:r1:ORD-20260404-1003:shipped"]
    item = items[0]
    assert item["severity"] == "high"
    assert item["entity_ref"] == {"kind": "order", "id": "ORD-20260404-1003"}
    assert item["status"] == "open"


def test_r1_finding_disappears_once_the_serving_projection_catches_up(client: TestClient):
    conn = client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO pipeline_events
            (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at)
        VALUES ('evt-r1-test', 'orders.status', 'default', 'ORD-20260404-1003',
                'order.status.shipped', NULL, NOW())
        """
    )
    assert (
        len(client.get("/v1/ops/exceptions", params={"source": "reconciliation"}).json()["items"])
        == 1
    )

    conn.execute("UPDATE orders_v2 SET status = 'shipped' WHERE order_id = 'ORD-20260404-1003'")

    response = client.get("/v1/ops/exceptions", params={"source": "reconciliation"})
    assert response.json()["items"] == []


def test_r2_detects_a_stuck_replay(client: TestClient):
    conn = client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO dead_letter_events
            (event_id, tenant_id, event_type, payload, failure_reason, failure_detail,
             received_at, retry_count, last_retried_at, status)
        VALUES ('evt-stuck-replay', 'default', 'order.created', '{}', 'kafka_error', 'x',
                NOW() - INTERVAL '20 minutes', 1, NOW() - INTERVAL '15 minutes', 'replay_pending')
        """
    )

    response = client.get("/v1/ops/exceptions", params={"source": "reconciliation"})

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["item_id"] for item in items] == ["rc:r2:evt-stuck-replay"]
    assert items[0]["severity"] == "medium"
    assert items[0]["entity_ref"] == {"kind": "event", "id": "evt-stuck-replay"}


def test_reconciliation_reads_are_idempotent_under_repeated_calls(client: TestClient):
    # I10: running the checks on every read must never write serving state or
    # duplicate overlay rows.
    conn = client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO pipeline_events
            (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at)
        VALUES ('evt-r1-test', 'orders.status', 'default', 'ORD-20260404-1003',
                'order.status.shipped', NULL, NOW())
        """
    )

    first = client.get("/v1/ops/exceptions", params={"source": "reconciliation"}).json()
    second = client.get("/v1/ops/exceptions", params={"source": "reconciliation"}).json()
    third = client.get("/v1/ops/exceptions", params={"source": "reconciliation"}).json()

    assert first == second == third
    assert len(first["items"]) == 1


# --- mutations: auth, 409/404, acknowledge/resolve, auto-resolve ------------


def test_acknowledge_requires_an_api_key(authed_client: TestClient):
    response = authed_client.post("/v1/ops/exceptions/wh:hook:evt/acknowledge")
    assert response.status_code == 401


def test_readonly_key_cannot_mutate(authed_client: TestClient, auth_headers):
    response = authed_client.post(
        "/v1/ops/exceptions/wh:hook:evt/acknowledge", headers=auth_headers["readonly"]
    )
    assert response.status_code == 403


def test_deadletter_item_mutation_is_rejected_with_409(authed_client: TestClient, auth_headers):
    response = authed_client.post(
        "/v1/ops/exceptions/dl:evt-004/acknowledge", headers=auth_headers["ops"]
    )
    assert response.status_code == 409


def test_unknown_item_id_returns_404(authed_client: TestClient, auth_headers):
    response = authed_client.post(
        "/v1/ops/exceptions/rc:does-not-exist/acknowledge", headers=auth_headers["ops"]
    )
    assert response.status_code == 404


def test_acknowledge_then_resolve_lifecycle(authed_client: TestClient, auth_headers):
    conn = authed_client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO pipeline_events
            (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at)
        VALUES ('evt-r1-test', 'orders.status', 'default', 'ORD-20260404-1003',
                'order.status.shipped', NULL, NOW())
        """
    )
    ops = auth_headers["ops"]
    item_id = "rc:r1:ORD-20260404-1003:shipped"
    # First GET seeds the overlay row for this finding.
    authed_client.get("/v1/ops/exceptions", params={"source": "reconciliation"}, headers=ops)

    ack = authed_client.post(f"/v1/ops/exceptions/{item_id}/acknowledge", headers=ops)
    assert ack.status_code == 200
    assert ack.json() == {"item_id": item_id, "status": "acknowledged"}

    still_listed = authed_client.get(
        "/v1/ops/exceptions", params={"source": "reconciliation"}, headers=ops
    )
    assert [item["status"] for item in still_listed.json()["items"]] == ["acknowledged"]

    resolve = authed_client.post(
        f"/v1/ops/exceptions/{item_id}/resolve", headers=ops, json={"note": "fixed manually"}
    )
    assert resolve.status_code == 200
    assert resolve.json() == {"item_id": item_id, "status": "resolved"}

    default_view = authed_client.get(
        "/v1/ops/exceptions", params={"source": "reconciliation"}, headers=ops
    )
    assert default_view.json()["items"] == []

    resolved_view = authed_client.get(
        "/v1/ops/exceptions",
        params={"source": "reconciliation", "status": "resolved"},
        headers=ops,
    )
    assert [item["item_id"] for item in resolved_view.json()["items"]] == [item_id]

    stats = authed_client.get("/v1/ops/exceptions/stats", headers=ops).json()
    assert stats["manual_resolutions"] == 1


def test_scan_cap_reports_truncation_in_list_and_stats(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    # S-8: the demo seed has two dead-letter rows; a cap of 1 truncates the
    # inbox's native source, which both surfaces report — never a silent cut.
    data = client.get("/v1/ops/exceptions").json()
    assert data["scan_truncated"] is False
    assert client.get("/v1/ops/exceptions/stats").json()["scan_truncated"] is False

    monkeypatch.setenv("AGENTFLOW_OPS_INBOX_SCAN_LIMIT", "1")

    data = client.get("/v1/ops/exceptions").json()
    assert data["scan_truncated"] is True
    assert len(data["items"]) == 1
    assert client.get("/v1/ops/exceptions/stats").json()["scan_truncated"] is True


def test_truncated_webhook_scan_never_auto_resolves_out_of_window_items(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    # S-8 guard: a truncated scan cannot prove absence. Without the guard,
    # the capped gather would pass an incomplete seen-set to auto-resolve and
    # mark the still-dead out-of-window delivery resolved — and since its
    # `updated_at` never advances, the later upsert could not reopen it.
    from datetime import UTC, datetime, timedelta

    from src.serving.control_plane import get_control_plane_store
    from src.serving.control_plane.embedded import ensure_webhook_delivery_queue_table

    store = get_control_plane_store(client.app)
    conn = store._conn
    ensure_webhook_delivery_queue_table(conn)
    now = datetime.now(UTC)
    for webhook_id, event_id, updated_at in (
        ("wh-old", "evt-old", now - timedelta(minutes=10)),
        ("wh-new", "evt-new", now),
    ):
        conn.execute(
            """
            INSERT INTO webhook_delivery_queue
                (webhook_id, event_id, tenant, event_type, body, status, attempts,
                 last_error, created_at, updated_at)
            VALUES (?, ?, 'default', 'order.created', '{}', 'dead', 5,
                    'connection refused', ?, ?)
            """,
            [webhook_id, event_id, updated_at, updated_at],
        )

    # Both enter the overlay while the scan is unbounded.
    data = client.get("/v1/ops/exceptions", params={"source": "webhook_delivery"}).json()
    assert {item["item_id"] for item in data["items"]} == {
        "wh:wh-old:evt-old",
        "wh:wh-new:evt-new",
    }

    # Capped to the newest row: truncated, and wh-old is out of the window.
    monkeypatch.setenv("AGENTFLOW_OPS_INBOX_SCAN_LIMIT", "1")
    data = client.get("/v1/ops/exceptions", params={"source": "webhook_delivery"}).json()
    assert data["scan_truncated"] is True
    assert [item["item_id"] for item in data["items"]] == ["wh:wh-new:evt-new"]

    # Uncapped again: wh-old is still open — the truncated scan resolved
    # nothing behind the operator's back.
    monkeypatch.delenv("AGENTFLOW_OPS_INBOX_SCAN_LIMIT")
    data = client.get("/v1/ops/exceptions", params={"source": "webhook_delivery"}).json()
    status_by_id = {item["item_id"]: item["status"] for item in data["items"]}
    assert status_by_id["wh:wh-old:evt-old"] == "open"
    assert status_by_id["wh:wh-new:evt-new"] == "open"


def test_auto_resolve_when_the_finding_no_longer_reproduces(
    authed_client: TestClient, auth_headers
):
    # A reconciliation finding is computed on read, not a persistent row like
    # a dead-letter/webhook item — once the underlying mismatch clears there
    # is nothing left to render (no live title/detail/entity_ref), so the
    # item disappears from the feed entirely rather than reappearing under
    # `status=resolved`. The overlay row itself is still auto-resolved
    # behind the scenes, verified here through `manual_resolutions` — a raw
    # count over the overlay table, independent of what's currently live.
    conn = authed_client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO pipeline_events
            (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at)
        VALUES ('evt-r1-test', 'orders.status', 'default', 'ORD-20260404-1003',
                'order.status.shipped', NULL, NOW())
        """
    )
    ops = auth_headers["ops"]
    authed_client.get("/v1/ops/exceptions", params={"source": "reconciliation"}, headers=ops)

    conn.execute("UPDATE orders_v2 SET status = 'shipped' WHERE order_id = 'ORD-20260404-1003'")

    default_view = authed_client.get(
        "/v1/ops/exceptions", params={"source": "reconciliation"}, headers=ops
    )
    resolved_view = authed_client.get(
        "/v1/ops/exceptions",
        params={"source": "reconciliation", "status": "resolved"},
        headers=ops,
    )
    assert default_view.json()["items"] == []
    assert resolved_view.json()["items"] == []

    stats = authed_client.get("/v1/ops/exceptions/stats", headers=ops).json()
    # Auto-resolved, not a human decision — excluded from the manual KPI.
    assert stats["manual_resolutions"] == 0
