"""Center cross-branch summary from the journal (ADR 0012 §9, N8).

A pure read over ``pipeline_events`` — no new store. For every known branch it
reports the seeded baseline, the live delta accrued this lifecycle, and a
last-seen timestamp. A branch that has sent nothing (asleep or just booted)
shows baseline + null last-seen + a ``waking`` status, **never** an error — the
sleep behaviour is visible by design.
"""

from __future__ import annotations

from datetime import datetime

import duckdb

from src.serving.node.seed import NODE_BASELINE_TOPIC

# All branches the center reports on, in a stable display order (msk hub first).
CROSS_BRANCH_ORDER: tuple[str, ...] = ("msk", "spb", "ekb")

CROSS_BRANCH_HINT = "open a branch Space to see its events flow to the hub"


def cross_branch_summary(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Per-branch baseline / live-delta / last-seen, one row per known branch.

    Silent branches are included with zero delta and a null last-seen (N8), so
    the view degrades gracefully rather than dropping or erroring on them."""
    baseline_rows = conn.execute(
        "SELECT branch, COUNT(*) FROM pipeline_events WHERE topic = ? AND branch IS NOT NULL "
        "GROUP BY branch",
        [NODE_BASELINE_TOPIC],
    ).fetchall()
    baseline = {str(branch): int(count) for branch, count in baseline_rows}

    live_rows = conn.execute(
        "SELECT branch, COUNT(*), MAX(processed_at) FROM pipeline_events "
        "WHERE topic IN ('events.validated', 'events.deadletter') AND branch IS NOT NULL "
        "GROUP BY branch"
    ).fetchall()
    live = {str(branch): (int(count), last_seen) for branch, count, last_seen in live_rows}

    summary = []
    for branch in CROSS_BRANCH_ORDER:
        live_delta, last_seen = live.get(branch, (0, None))
        summary.append(
            {
                "branch": branch,
                "baseline": baseline.get(branch, 0),
                "live_delta": live_delta,
                "last_seen": last_seen.isoformat() if isinstance(last_seen, datetime) else None,
                "status": "live" if live_delta > 0 else "waking",
            }
        )
    return summary
