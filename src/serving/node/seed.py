"""Branch-scoped boot baseline for the three-node demo (ADR 0012 §7, N6/N11).

The demo entity tables (``orders_v2`` …) are a shared catalog with no branch
column, so branch attribution lives on the ``pipeline_events`` journal. This
seed lays down a deterministic per-branch **baseline** under a distinct topic
(``node.baseline``) so a center-first visitor sees a coherent cross-branch
picture before any live event arrives (N8 baseline half). It is a pure function
of the branch, so any node re-seeds to the same baseline on every restart (N11);
standalone gets none, keeping today's demo byte-identical (N1).

The distinct topic keeps these rows inert to every existing journal scan
(freshness/webhook/lineage/stage-clock all filter on their own topics), and lets
the cross-branch view (step 5) tell the seeded baseline apart from the live
delta.
"""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb

from src.serving.node.config import NodeConfig

NODE_BASELINE_TOPIC = "node.baseline"

# The center's HQ (msk) carries the largest baseline; the two RU regional
# warehouses are smaller. Fixed figures → a deterministic baseline (N11).
BASELINE_ROWS_BY_BRANCH: dict[str, int] = {"msk": 8, "spb": 4, "ekb": 4}

# Deterministic branch order (KNOWN_BRANCHES is an unordered frozenset).
_ALL_BRANCHES: tuple[str, ...] = ("msk", "spb", "ekb")


def seed_node_baseline(conn: duckdb.DuckDBPyConnection, config: NodeConfig) -> None:
    """Seed the per-branch baseline. Center seeds all three branches; an edge
    seeds only its own; standalone is a no-op. Idempotent: clears any prior
    baseline then re-lays the fixed set, so a restart yields the same baseline."""
    if config.is_standalone or config.branch is None:
        return

    branches = _ALL_BRANCHES if config.is_center else (config.branch,)

    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM pipeline_events WHERE topic = ?", [NODE_BASELINE_TOPIC])
        now = datetime.now(UTC)
        for branch in branches:
            for i in range(BASELINE_ROWS_BY_BRANCH[branch]):
                conn.execute(
                    """
                    INSERT INTO pipeline_events (
                        event_id, topic, tenant_id, entity_id, event_type,
                        latency_ms, processed_at, branch
                    )
                    VALUES (?, ?, 'default', NULL, 'node.baseline', NULL, ?, ?)
                    """,
                    [f"node-baseline-{branch}-{i}", NODE_BASELINE_TOPIC, now, branch],
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
