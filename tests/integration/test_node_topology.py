"""Three-node demo topology — full-app node invariants (ADR 0012 / build §13).

Every case boots the real ``app`` via ``TestClient`` (in-memory DuckDB, no
Docker). Covered here: N1 (standalone unchanged), N2 (mounted iff center),
N3 (bearer auth vs demo-key), N4 (apply + branch tag), N5 (idempotency),
N12 (role/branch guard). N6/N8/N11 land with the seed + cross-branch view.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.ingestion.producers.event_producer import generate_order
from src.serving.api.main import app
from src.serving.node.seed import BASELINE_ROWS_BY_BRANCH, NODE_BASELINE_TOPIC

pytestmark = pytest.mark.integration

_TOKEN = "test-center-node-token"  # noqa: S105 — test fixture, not a real secret
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _order_event() -> dict:
    """A real canonical order event (producer-shaped, valid uuid event_id) — the
    exact dict the edge emitter forwards. Ids are the producer's own so schema
    validation passes; tests read them back off the returned dict."""
    _topic, model = generate_order()
    return json.loads(model.model_dump_json())


@pytest.fixture
def standalone_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("AGENTFLOW_NODE_ROLE", raising=False)
    monkeypatch.setenv("AGENTFLOW_DEMO_MODE", "true")
    monkeypatch.setenv("AGENTFLOW_SEED_ON_BOOT", "true")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def center_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("AGENTFLOW_NODE_ROLE", "center")
    monkeypatch.setenv("AGENTFLOW_NODE_BRANCH", "msk")
    monkeypatch.setenv("AGENTFLOW_NODE_TOKEN", _TOKEN)
    monkeypatch.setenv("AGENTFLOW_DEMO_MODE", "true")
    monkeypatch.setenv("AGENTFLOW_SEED_ON_BOOT", "true")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def edge_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("AGENTFLOW_NODE_ROLE", "edge")
    monkeypatch.setenv("AGENTFLOW_NODE_BRANCH", "spb")
    monkeypatch.setenv("AGENTFLOW_NODE_CENTER_URL", "https://center.invalid")
    monkeypatch.setenv("AGENTFLOW_NODE_TOKEN", _TOKEN)
    monkeypatch.setenv("AGENTFLOW_NODE_EMITTER_ENABLED", "false")
    monkeypatch.setenv("AGENTFLOW_DEMO_MODE", "true")
    monkeypatch.setenv("AGENTFLOW_SEED_ON_BOOT", "true")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def edge_emitting_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Emitter on, but a long interval + large batch so it applies at most one
    # event locally and never forwards during the test (no network to the
    # unreachable center).
    monkeypatch.setenv("AGENTFLOW_NODE_ROLE", "edge")
    monkeypatch.setenv("AGENTFLOW_NODE_BRANCH", "ekb")
    monkeypatch.setenv("AGENTFLOW_NODE_CENTER_URL", "https://center.invalid")
    monkeypatch.setenv("AGENTFLOW_NODE_TOKEN", _TOKEN)
    monkeypatch.setenv("AGENTFLOW_NODE_EMIT_INTERVAL_SECONDS", "3600")
    monkeypatch.setenv("AGENTFLOW_NODE_EMIT_BATCH_SIZE", "1000")
    monkeypatch.setenv("AGENTFLOW_DEMO_MODE", "true")
    monkeypatch.setenv("AGENTFLOW_SEED_ON_BOOT", "true")
    with TestClient(app) as client:
        yield client


# --- N1: standalone is byte-identical -------------------------------------


def test_standalone_resolves_standalone_role(standalone_client: TestClient) -> None:
    assert standalone_client.app.state.node_role == "standalone"
    assert standalone_client.app.state.node_branch is None
    assert standalone_client.app.state.node_config.is_standalone


def test_standalone_has_no_emitter_task(standalone_client: TestClient) -> None:
    assert getattr(standalone_client.app.state, "node_emitter_task", None) is None


def test_standalone_health_still_serves(standalone_client: TestClient) -> None:
    assert standalone_client.get("/v1/health").status_code == 200


def test_ingest_absent_from_public_schema(standalone_client: TestClient) -> None:
    # Internal node-to-node endpoint — never in the public agent catalog.
    schema = standalone_client.get("/openapi.json").json()
    assert "/v1/node/events" not in schema.get("paths", {})


# --- N2: mounted iff role == center ---------------------------------------


def test_standalone_ingest_is_404(standalone_client: TestClient) -> None:
    resp = standalone_client.post(
        "/v1/node/events", json={"origin_branch": "spb", "events": []}, headers=_AUTH
    )
    assert resp.status_code == 404


def test_edge_ingest_is_404_even_with_token(edge_client: TestClient) -> None:
    # N12: a non-center node refuses ingest even with a valid token.
    resp = edge_client.post(
        "/v1/node/events", json={"origin_branch": "spb", "events": []}, headers=_AUTH
    )
    assert resp.status_code == 404


def test_center_ingest_accepts_empty_batch(center_client: TestClient) -> None:
    resp = center_client.post(
        "/v1/node/events", json={"origin_branch": "spb", "events": []}, headers=_AUTH
    )
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 0, "applied": 0, "dead_lettered": 0, "duplicates": 0}


# --- Emitter wiring: started only in edge role ----------------------------


def test_edge_boot_starts_emitter(edge_emitting_client: TestClient) -> None:
    task = edge_emitting_client.app.state.node_emitter_task
    assert isinstance(task, asyncio.Task)
    assert edge_emitting_client.app.state.node_emitter is not None


def test_center_boot_has_no_emitter(center_client: TestClient) -> None:
    assert getattr(center_client.app.state, "node_emitter_task", None) is None


# --- N6: branch-scoped baseline seed --------------------------------------


def _baseline_counts(client: TestClient) -> dict[str, int]:
    rows = client.app.state.query_engine._conn.execute(
        "SELECT branch, COUNT(*) FROM pipeline_events WHERE topic = ? GROUP BY branch",
        [NODE_BASELINE_TOPIC],
    ).fetchall()
    return {str(branch): int(count) for branch, count in rows}


def test_center_boot_seeds_all_branch_baseline(center_client: TestClient) -> None:
    assert _baseline_counts(center_client) == BASELINE_ROWS_BY_BRANCH


def test_edge_boot_seeds_only_its_branch(edge_client: TestClient) -> None:
    # edge_client is the spb edge (emitter off).
    assert _baseline_counts(edge_client) == {"spb": BASELINE_ROWS_BY_BRANCH["spb"]}


def test_standalone_boot_seeds_no_branch_baseline(standalone_client: TestClient) -> None:
    assert _baseline_counts(standalone_client) == {}


# --- N8: center cross-branch view + graceful degradation ------------------


def test_center_cross_branch_view_lists_all_branches(center_client: TestClient) -> None:
    resp = center_client.get("/v1/node/branches", headers={"X-API-Key": "demo-key"})
    assert resp.status_code == 200
    data = resp.json()
    by_branch = {row["branch"]: row for row in data["branches"]}
    assert set(by_branch) == {"msk", "spb", "ekb"}
    assert by_branch["msk"]["baseline"] == BASELINE_ROWS_BY_BRANCH["msk"]
    # N8: no live events yet — silent branches are waking, not errors.
    assert by_branch["spb"]["status"] == "waking"
    assert by_branch["spb"]["last_seen"] is None
    assert data["hint"]


def test_center_cross_branch_view_reflects_ingested_event(center_client: TestClient) -> None:
    # N4 (metric moved): an edge->center event lifts the spb live delta.
    event = _order_event()
    center_client.post(
        "/v1/node/events", json={"origin_branch": "spb", "events": [event]}, headers=_AUTH
    )
    resp = center_client.get("/v1/node/branches", headers={"X-API-Key": "demo-key"})
    by_branch = {row["branch"]: row for row in resp.json()["branches"]}
    assert by_branch["spb"]["live_delta"] >= 1
    assert by_branch["spb"]["last_seen"] is not None
    assert by_branch["spb"]["status"] == "live"
    # The hub's own branch stays baseline-only (it aggregates, does not emit).
    assert by_branch["msk"]["status"] == "waking"


def test_edge_cross_branch_view_is_404(edge_client: TestClient) -> None:
    resp = edge_client.get("/v1/node/branches", headers={"X-API-Key": "demo-key"})
    assert resp.status_code == 404


def test_standalone_cross_branch_view_is_404(standalone_client: TestClient) -> None:
    resp = standalone_client.get("/v1/node/branches", headers={"X-API-Key": "demo-key"})
    assert resp.status_code == 404


# --- N3 / N10: bearer auth, not the demo-key ------------------------------


def test_center_ingest_missing_bearer_is_401(center_client: TestClient) -> None:
    resp = center_client.post("/v1/node/events", json={"origin_branch": "spb", "events": []})
    assert resp.status_code == 401


def test_center_ingest_public_demo_key_is_rejected(center_client: TestClient) -> None:
    # The public demo-key (X-API-Key) is not the node token — no bearer → 401.
    resp = center_client.post(
        "/v1/node/events",
        json={"origin_branch": "spb", "events": []},
        headers={"X-API-Key": "demo-key"},
    )
    assert resp.status_code == 401


def test_center_ingest_wrong_token_is_403(center_client: TestClient) -> None:
    resp = center_client.post(
        "/v1/node/events",
        json={"origin_branch": "spb", "events": []},
        headers={"Authorization": "Bearer not-the-token"},
    )
    assert resp.status_code == 403


# --- N4: apply via _process_event, branch-tag the journal, move the metric -


def test_center_applies_event_and_tags_branch(center_client: TestClient) -> None:
    event = _order_event()
    resp = center_client.post(
        "/v1/node/events", json={"origin_branch": "spb", "events": [event]}, headers=_AUTH
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 1
    assert body["applied"] == 1
    assert body["dead_lettered"] == 0

    conn = center_client.app.state.query_engine._conn
    # Journal row carries branch=spb (N4).
    branches = conn.execute(
        "SELECT DISTINCT branch FROM pipeline_events "
        "WHERE event_id = ? AND topic = 'events.validated'",
        [event["event_id"]],
    ).fetchall()
    assert branches == [("spb",)]
    # The order landed on the center's serving surface (metric moves).
    order_count = conn.execute(
        "SELECT COUNT(*) FROM orders_v2 WHERE order_id = ?", [event["order_id"]]
    ).fetchone()
    assert order_count is not None
    assert order_count[0] == 1


# --- N5: idempotency — re-POST the same batch does not double-count --------


def test_center_ingest_is_idempotent(center_client: TestClient) -> None:
    event = _order_event()
    batch = {"origin_branch": "spb", "events": [event]}

    first = center_client.post("/v1/node/events", json=batch, headers=_AUTH)
    assert first.status_code == 200
    assert first.json()["applied"] == 1

    second = center_client.post("/v1/node/events", json=batch, headers=_AUTH)
    assert second.status_code == 200
    body = second.json()
    assert body["applied"] == 0
    assert body["duplicates"] == 1

    conn = center_client.app.state.query_engine._conn
    validated = conn.execute(
        "SELECT COUNT(*) FROM pipeline_events WHERE event_id = ? AND topic = 'events.validated'",
        [event["event_id"]],
    ).fetchone()
    assert validated is not None
    assert validated[0] == 1


# --- N12: role/branch guard -----------------------------------------------


def test_center_rejects_unknown_origin_branch(center_client: TestClient) -> None:
    resp = center_client.post(
        "/v1/node/events",
        json={"origin_branch": "tokyo", "events": []},
        headers=_AUTH,
    )
    assert resp.status_code == 422


def test_center_rejects_oversized_batch(center_client: TestClient) -> None:
    # The size bound is a body-shape guard (422) checked before any apply, so
    # the event contents are irrelevant here.
    events = [{} for _ in range(501)]
    resp = center_client.post(
        "/v1/node/events", json={"origin_branch": "spb", "events": events}, headers=_AUTH
    )
    assert resp.status_code == 422
