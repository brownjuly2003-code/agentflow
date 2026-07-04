"""Branch-scoped baseline seed — determinism + scoping (ADR 0012 §7, N6/N11)."""

from __future__ import annotations

import duckdb

from src.processing.local_pipeline import _ensure_tables
from src.serving.node.config import NodeConfig
from src.serving.node.seed import (
    BASELINE_ROWS_BY_BRANCH,
    NODE_BASELINE_TOPIC,
    seed_node_baseline,
)

_TOKEN = "seed-node-token"  # noqa: S105 — test fixture, not a real secret


def _conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    _ensure_tables(conn)
    return conn


def _counts_by_branch(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT branch, COUNT(*) FROM pipeline_events WHERE topic = ? GROUP BY branch",
        [NODE_BASELINE_TOPIC],
    ).fetchall()
    return {str(branch): int(count) for branch, count in rows}


def _snapshot(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT event_id, branch FROM pipeline_events WHERE topic = ? ORDER BY event_id",
        [NODE_BASELINE_TOPIC],
    ).fetchall()
    return [(str(a), str(b)) for a, b in rows]


def test_standalone_seeds_no_baseline() -> None:
    conn = _conn()
    seed_node_baseline(conn, NodeConfig(role="standalone"))
    assert _counts_by_branch(conn) == {}


def test_center_seeds_all_branches() -> None:
    conn = _conn()
    seed_node_baseline(conn, NodeConfig(role="center", branch="msk", token=_TOKEN))
    assert _counts_by_branch(conn) == BASELINE_ROWS_BY_BRANCH


def test_edge_seeds_only_its_branch() -> None:
    conn = _conn()
    seed_node_baseline(
        conn,
        NodeConfig(role="edge", branch="spb", center_url="https://c", token=_TOKEN),
    )
    assert _counts_by_branch(conn) == {"spb": BASELINE_ROWS_BY_BRANCH["spb"]}


def test_reseed_is_deterministic() -> None:
    # N11: re-seeding (the restart analog) yields the same baseline, never a
    # doubled one.
    conn = _conn()
    config = NodeConfig(role="center", branch="msk", token=_TOKEN)
    seed_node_baseline(conn, config)
    first = _snapshot(conn)

    seed_node_baseline(conn, config)
    assert _snapshot(conn) == first


def test_baseline_topic_is_disjoint_from_live_topics() -> None:
    # The baseline must not masquerade as a live validated/deadletter event.
    conn = _conn()
    seed_node_baseline(conn, NodeConfig(role="center", branch="msk", token=_TOKEN))
    live = conn.execute(
        "SELECT COUNT(*) FROM pipeline_events "
        "WHERE topic IN ('events.validated', 'events.deadletter')"
    ).fetchone()
    assert live is not None
    assert live[0] == 0
