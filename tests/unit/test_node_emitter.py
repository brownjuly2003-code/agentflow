"""Edge emitter — produce/apply seam and cold-center tolerance (ADR 0012 §6).

Unit-level (no app boot, no network): an in-memory DuckDB for the local apply
and a hand-rolled async client for the forward path. Covers N7 (same dict
applied locally and forwarded) and N9 (a cold/unreachable center is tolerated,
never raised).
"""

from __future__ import annotations

import duckdb
import httpx

from src.processing.local_pipeline import _ensure_tables
from src.serving.node.config import NodeConfig
from src.serving.node.emitter import NodeEmitter

_TOKEN = "edge-node-token"  # noqa: S105 — test fixture, not a real secret


def _edge_config() -> NodeConfig:
    return NodeConfig(role="edge", branch="spb", center_url="https://center.example/", token=_TOKEN)


def _emitter(**kwargs) -> tuple[NodeEmitter, duckdb.DuckDBPyConnection]:
    conn = duckdb.connect(":memory:")
    _ensure_tables(conn)
    return NodeEmitter(config=_edge_config(), conn=conn, **kwargs), conn


class _CapturingClient:
    """Minimal async client double capturing the last POST."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.calls: list[dict] = []

    async def post(self, url: str, json: dict, headers: dict) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "headers": headers})
        return httpx.Response(self.status_code)


class _ColdClient:
    """Async client double that always fails the connection (cold/asleep hub)."""

    def __init__(self) -> None:
        self.attempts = 0

    async def post(self, url: str, json: dict, headers: dict) -> httpx.Response:
        self.attempts += 1
        raise httpx.ConnectError("center is asleep")


# --- N7: local apply and forwarded payload are the same canonical dict -----


def test_produce_local_tags_branch_and_applies() -> None:
    emitter, conn = _emitter()
    event = emitter._produce_local()

    assert event["source_metadata"]["branch"] == "spb"
    row = conn.execute(
        "SELECT branch FROM pipeline_events "
        "WHERE event_id = ? AND topic IN ('events.validated', 'events.deadletter')",
        [event["event_id"]],
    ).fetchone()
    assert row is not None
    assert row[0] == "spb"


async def test_forward_posts_the_same_events_verbatim() -> None:
    emitter, _conn = _emitter()
    client = _CapturingClient()
    event = {"event_id": "evt-x", "event_type": "order.created"}

    ok = await emitter._forward(client, [event])

    assert ok is True
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://center.example/v1/node/events"
    assert call["json"]["origin_branch"] == "spb"
    assert call["json"]["events"] == [event]  # forwarded unchanged (N7)
    assert call["headers"]["Authorization"] == f"Bearer {_TOKEN}"


# --- N9: cold-center tolerance ---------------------------------------------


async def test_forward_tolerates_cold_center() -> None:
    emitter, _conn = _emitter(max_retries=3, backoff_base_seconds=0.0)
    client = _ColdClient()

    # Must not raise even though every attempt fails.
    ok = await emitter._forward(client, [{"event_id": "evt-x"}])

    assert ok is False
    assert client.attempts == 3  # bounded retries, then drop


async def test_forward_drops_rejected_batch_without_retry() -> None:
    emitter, _conn = _emitter(max_retries=3, backoff_base_seconds=0.0)
    client = _CapturingClient(status_code=403)

    ok = await emitter._forward(client, [{"event_id": "evt-x"}])

    assert ok is False
    assert len(client.calls) == 1  # a rejected batch is not retried


async def test_forward_empty_batch_is_noop() -> None:
    emitter, _conn = _emitter()
    client = _CapturingClient()

    ok = await emitter._forward(client, [])

    assert ok is True
    assert client.calls == []
