"""Integration tests for the stuck-orders worklist —
GET /v1/ops/stuck-orders (ops-surfaces-spec.md §3, D3). Exercises the demo
story pin (I7: default view = exactly ORD-20260404-1004), the SLA-stage
contract block (I2), stage-vocabulary tolerance (I4), and fallback-clock
honesty (I12). Tenant scoping (I8) and the no-third-path ratchet (I1) live in
test_tenant_isolation.py and test_control_plane_store.py respectively — same
pattern as test_order_timeline.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "stuck-orders.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db_path))
    monkeypatch.setenv("SERVING_BACKEND", "duckdb")
    monkeypatch.setenv("AGENTFLOW_AUTH_DISABLED", "true")

    with TestClient(app) as c:
        yield c


def test_default_view_returns_exactly_the_sole_breach(client: TestClient):
    # I7: ORD-20260404-1004 is 45 minutes into `pending` against a 30-minute
    # budget — the demo's sole breach.
    response = client.get("/v1/ops/stuck-orders")

    assert response.status_code == 200
    data = response.json()

    assert [item["order_id"] for item in data["items"]] == ["ORD-20260404-1004"]
    item = data["items"][0]
    assert item["status"] == "pending"
    assert item["clock"] == "journal"
    assert item["sla_minutes"] == 30
    assert item["overshoot_ratio"] == pytest.approx(1.5, rel=0.05)
    assert item["total_amount"] == 1890.0
    assert item["currency"] == "RUB"


def test_summary_reflects_the_full_open_order_set(client: TestClient):
    # Summary is always the full open-orders picture, independent of the
    # breach-only default filter on `items`.
    response = client.get("/v1/ops/stuck-orders")

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["open_by_stage"] == {"pending": 2, "confirmed": 2, "shipped": 1}
    assert summary["breached_by_stage"] == {"pending": 1}


def test_include_within_sla_returns_the_whole_open_worklist(client: TestClient):
    response = client.get("/v1/ops/stuck-orders", params={"include_within_sla": "true"})

    assert response.status_code == 200
    data = response.json()
    order_ids = [item["order_id"] for item in data["items"]]

    assert set(order_ids) == {
        "ORD-20260404-1002",
        "ORD-20260404-1003",
        "ORD-20260404-1004",
        "ORD-20260404-1007",
        "ORD-20260404-1008",
    }
    # Highest overshoot first — the breach still sorts to the top.
    assert order_ids[0] == "ORD-20260404-1004"
    ratios = [item["overshoot_ratio"] for item in data["items"]]
    assert ratios == sorted(ratios, reverse=True)


def test_terminal_orders_never_appear_even_with_include_within_sla(client: TestClient):
    response = client.get("/v1/ops/stuck-orders", params={"include_within_sla": "true"})

    assert response.status_code == 200
    order_ids = {item["order_id"] for item in response.json()["items"]}
    # ORD-1001/1005 delivered, ORD-1006 cancelled — terminal, never stuck.
    assert order_ids.isdisjoint({"ORD-20260404-1001", "ORD-20260404-1005", "ORD-20260404-1006"})


def test_stage_filter_narrows_to_one_ladder_stage(client: TestClient):
    response = client.get(
        "/v1/ops/stuck-orders", params={"stage": "confirmed", "include_within_sla": "true"}
    )

    assert response.status_code == 200
    data = response.json()
    assert {item["order_id"] for item in data["items"]} == {
        "ORD-20260404-1003",
        "ORD-20260404-1007",
    }
    assert all(item["status"] == "confirmed" for item in data["items"])


def test_pagination_shape(client: TestClient):
    response = client.get(
        "/v1/ops/stuck-orders", params={"include_within_sla": "true", "page": 1, "page_size": 2}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["pagination"] == {"page": 1, "page_size": 2, "total": 5, "pages": 3}


def test_order_without_stage_rows_reports_fallback_clock(client: TestClient):
    # I12: an order written outside the stage-row writer degrades honestly
    # to the created_at fallback instead of pretending to have a journal
    # clock.
    conn = client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO orders_v2 (order_id, user_id, status, total_amount, currency, created_at)
        VALUES ('ORD-BYPASS-1', 'USR-10001', 'confirmed', 500.0, 'RUB',
                NOW() - INTERVAL '10 minutes')
        """
    )

    response = client.get("/v1/ops/stuck-orders", params={"include_within_sla": "true"})

    assert response.status_code == 200
    item = next(i for i in response.json()["items"] if i["order_id"] == "ORD-BYPASS-1")
    assert item["clock"] == "fallback"
    assert 0 < item["in_stage_seconds"] < 900


def test_order_with_status_outside_the_ladder_never_crashes_or_appears(client: TestClient):
    # I4: a status the contract's stages: block doesn't know about is not
    # part of the ladder query — it never surfaces and never 500s.
    conn = client.app.state.query_engine._conn
    conn.execute(
        """
        INSERT INTO orders_v2 (order_id, user_id, status, total_amount, currency, created_at)
        VALUES ('ORD-WEIRD-STATUS', 'USR-10001', 'on_hold', 500.0, 'RUB',
                NOW() - INTERVAL '10 minutes')
        """
    )

    response = client.get("/v1/ops/stuck-orders", params={"include_within_sla": "true"})

    assert response.status_code == 200
    order_ids = {item["order_id"] for item in response.json()["items"]}
    assert "ORD-WEIRD-STATUS" not in order_ids
