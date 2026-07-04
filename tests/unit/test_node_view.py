"""Cross-branch summary — graceful degradation over the journal (ADR 0012 §9, N8)."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb

from src.processing.local_pipeline import _ensure_tables
from src.serving.node.config import NodeConfig
from src.serving.node.seed import BASELINE_ROWS_BY_BRANCH, seed_node_baseline
from src.serving.node.view import CROSS_BRANCH_ORDER, cross_branch_summary

_TOKEN = "view-node-token"  # noqa: S105 — test fixture, not a real secret


def _conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    _ensure_tables(conn)
    return conn


def _add_live(conn: duckdb.DuckDBPyConnection, branch: str, event_id: str) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_events (
            event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at, branch
        )
        VALUES (?, 'events.validated', 'default', NULL, 'order.created', 5, ?, ?)
        """,
        [event_id, datetime.now(UTC), branch],
    )


def test_summary_lists_every_known_branch_even_when_silent() -> None:
    conn = _conn()
    seed_node_baseline(conn, NodeConfig(role="center", branch="msk", token=_TOKEN))

    summary = cross_branch_summary(conn)

    assert [row["branch"] for row in summary] == list(CROSS_BRANCH_ORDER)
    for row in summary:
        # N8: silent branches degrade to waking + null last-seen, never dropped.
        assert row["baseline"] == BASELINE_ROWS_BY_BRANCH[row["branch"]]
        assert row["live_delta"] == 0
        assert row["last_seen"] is None
        assert row["status"] == "waking"


def test_summary_reflects_live_delta_and_last_seen() -> None:
    conn = _conn()
    seed_node_baseline(conn, NodeConfig(role="center", branch="msk", token=_TOKEN))
    _add_live(conn, "spb", "evt-live-1")
    _add_live(conn, "spb", "evt-live-2")

    by_branch = {row["branch"]: row for row in cross_branch_summary(conn)}

    assert by_branch["spb"]["live_delta"] == 2
    assert by_branch["spb"]["last_seen"] is not None
    assert by_branch["spb"]["status"] == "live"
    # A branch with no live events stays waking.
    assert by_branch["ekb"]["status"] == "waking"
    assert by_branch["ekb"]["last_seen"] is None


def test_summary_on_empty_journal_never_errors() -> None:
    # No baseline, no live events (a just-booted / fully asleep view).
    conn = _conn()
    summary = cross_branch_summary(conn)
    assert [row["branch"] for row in summary] == list(CROSS_BRANCH_ORDER)
    assert all(row["baseline"] == 0 and row["status"] == "waking" for row in summary)
