"""Smoke for scripts/benchmark_scale_own_data.py against live ClickHouse.

Runs the S13 scale harness end-to-end at a tiny --days so CI proves the
generator SQL, the analyst queries, and every §12 correctness check execute
against a real server — the at-scale numbers themselves are stand work
(docs/perf/). Gated on ``CLICKHOUSE_LIVE_HOST`` like test_serving_bridge.py
(CI's test-integration job provides one).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIVE_HOST = os.getenv("CLICKHOUSE_LIVE_HOST")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_docker,
    pytest.mark.skipif(
        not LIVE_HOST,
        reason="CLICKHOUSE_LIVE_HOST not configured (live ClickHouse required)",
    ),
]


def test_scale_harness_smoke(tmp_path: Path) -> None:
    report_json = tmp_path / "scale-report.json"
    report_md = tmp_path / "scale-report.md"
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "benchmark_scale_own_data.py"),
            "--host",
            LIVE_HOST or "localhost",
            "--port",
            os.getenv("CLICKHOUSE_LIVE_PORT", "8123"),
            "--user",
            os.getenv("CLICKHOUSE_LIVE_USER", "agentflow"),
            "--password",
            os.getenv("CLICKHOUSE_LIVE_PASSWORD", "agentflow"),
            "--database",
            "rv_scale_smoke",
            "--days",
            "2",
            "--query-repeats",
            "1",
            "--drop-after",
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, (
        f"exit {result.returncode}\nstdout: {result.stdout[-4000:]}\nstderr: {result.stderr[-2000:]}"
    )

    report = json.loads(report_json.read_text(encoding="utf-8"))
    # 2 days at the §1 legend rate: 3,930 orders, 14,600 per-unit codes.
    assert report["orders"] == 3_930
    assert report["units"] == 14_600
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert not failed, f"correctness checks failed: {failed}"
    # Every analyst query executed and read rows.
    assert set(report["queries"]) == {
        "monthly_revenue_by_channel",
        "aov_by_channel",
        "sku_volume_ranking_marketplace",
        "branch_revenue_shares",
        "order_360_point_lookup",
        "marking_status_distribution",
    }
    assert report_md.read_text(encoding="utf-8").startswith("# At-scale proof")
