"""Integration tests for Order 360 — GET /v1/entity/order/{order_id}/timeline
(ops-surfaces-spec.md §2, D2). Exercises the demo story pins (I7), the PII-free
customer allow-list (I3), the fallback-clock honesty (I12), and the
error_rate re-pin by arithmetic (I9). Tenant scoping (I8) and the
no-third-path ratchet (I1) live in test_tenant_isolation.py and
test_control_plane_store.py respectively — same pattern as the other ops
surfaces.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app

pytestmark = pytest.mark.integration

_PII_FIELD_NAMES = ("first_name", "last_name", "email", "phone", "birth_date")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "order-timeline.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db_path))
    monkeypatch.setenv("SERVING_BACKEND", "duckdb")
    monkeypatch.setenv("AGENTFLOW_AUTH_DISABLED", "true")

    with TestClient(app) as c:
        yield c


def test_unknown_order_returns_404(client: TestClient):
    response = client.get("/v1/entity/order/ORD-DOES-NOT-EXIST/timeline")

    assert response.status_code == 404
    assert response.json() == {"detail": "order/ORD-DOES-NOT-EXIST not found"}


def test_delivered_order_carries_full_story(client: TestClient):
    # I7: ORD-20260404-1001 shows the full stage history, a >=3-row pipeline
    # trail, and the USR-10001 customer block.
    response = client.get("/v1/entity/order/ORD-20260404-1001/timeline")

    assert response.status_code == 200
    data = response.json()

    assert data["order"]["order_id"] == "ORD-20260404-1001"
    assert data["order"]["status"] == "delivered"

    assert data["stage"]["current"] == "delivered"
    assert data["stage"]["clock"] == "journal"
    assert data["stage"]["in_stage_seconds"] > 0

    statuses = [row["status"] for row in data["stage_history"]]
    assert statuses == ["pending", "confirmed", "shipped", "delivered"]
    # Ascending order — each stage entered later than the last.
    timestamps = [row["at"] for row in data["stage_history"]]
    assert timestamps == sorted(timestamps)

    assert len(data["pipeline_trail"]) >= 3
    trail_topics = {row["topic"] for row in data["pipeline_trail"]}
    assert "orders.status" not in trail_topics

    assert data["customer"] is not None
    assert data["customer"]["user_id"] == "USR-10001"
    assert data["customer"]["total_orders"] == 34


def test_pending_order_is_the_sole_breach_candidate(client: TestClient):
    # I7: ORD-20260404-1004's single pending stage entry sits at created_at,
    # 45 minutes ago — the demo's sole SLA breach once D3 wires budgets.
    response = client.get("/v1/entity/order/ORD-20260404-1004/timeline")

    assert response.status_code == 200
    data = response.json()

    assert data["stage"]["current"] == "pending"
    assert data["stage"]["clock"] == "journal"
    # ~45 minutes, allow for wall-clock drift while the test runs.
    assert 2600 < data["stage"]["in_stage_seconds"] < 2900
    assert [row["status"] for row in data["stage_history"]] == ["pending"]


def test_customer_block_is_a_pii_free_allowlist(client: TestClient):
    response = client.get("/v1/entity/order/ORD-20260404-1001/timeline")

    assert response.status_code == 200
    data = response.json()

    assert set(data["customer"].keys()) == {
        "user_id",
        "total_orders",
        "total_spent",
        "first_order_at",
        "last_order_at",
        "preferred_category",
    }
    # Structural belt-and-braces: no PII field name anywhere in the payload.
    for field_name in _PII_FIELD_NAMES:
        assert field_name not in response.text


def test_order_without_stage_rows_reports_fallback_clock(client: TestClient):
    # I12: an order written outside the stage-row writer (e.g. a bypass
    # insert) degrades honestly to the created_at fallback instead of
    # pretending to have a journal clock.
    conn = client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO orders_v2 (order_id, user_id, status, total_amount, currency, created_at)
        VALUES ('ORD-BYPASS-1', 'USR-10001', 'confirmed', 500.0, 'RUB',
                NOW() - INTERVAL '10 minutes')
        """
    )

    response = client.get("/v1/entity/order/ORD-BYPASS-1/timeline")

    assert response.status_code == 200
    data = response.json()
    assert data["stage"]["current"] == "confirmed"
    assert data["stage"]["clock"] == "fallback"
    assert data["stage_history"] == []
    assert 0 < data["stage"]["in_stage_seconds"] < 900


def test_stage_vocabulary_outside_the_ladder_never_crashes(client: TestClient):
    # I4 (D2's honest-degradation slice): a status the pipeline never wrote a
    # stage row for — here because it isn't even in the contract vocabulary
    # yet — still resolves cleanly rather than 500ing. No budget exists
    # pre-D3 either way, so sla_minutes/breached stay null.
    conn = client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO orders_v2 (order_id, user_id, status, total_amount, currency, created_at)
        VALUES ('ORD-WEIRD-STATUS', 'USR-10001', 'on_hold', 500.0, 'RUB',
                NOW() - INTERVAL '10 minutes')
        """
    )

    response = client.get("/v1/entity/order/ORD-WEIRD-STATUS/timeline")

    assert response.status_code == 200
    data = response.json()
    assert data["stage"]["current"] == "on_hold"
    assert data["stage"]["sla_minutes"] is None
    assert data["stage"]["breached"] is None


def test_error_rate_repins_by_arithmetic_after_seeded_stage_rows(client: TestClient):
    # I9: seeding 19 stage rows (spec §1.6) moves the demo error_rate
    # denominator. 2 dead-letter rows over 13 ambient/lineage + 19 stage
    # rows = 32 total in the 24h window.
    response = client.get("/v1/metrics/error_rate?window=24h")

    assert response.status_code == 200
    assert response.json()["value"] == pytest.approx(2 / 32)
