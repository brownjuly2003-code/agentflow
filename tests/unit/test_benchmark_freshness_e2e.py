from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from scripts import benchmark_freshness_e2e

ROOT = Path(__file__).resolve().parents[2]
ARCHIVED_S8_FRESHNESS_BLOB = "8332dc9d430c0c2e51d6756c21892d827b6f1ecf"


def test_parse_args_defaults_to_ignored_runtime_artifacts(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["benchmark_freshness_e2e.py"])

    args = benchmark_freshness_e2e.parse_args()

    assert args.report_md == str(
        benchmark_freshness_e2e.PROJECT_ROOT / ".artifacts" / "freshness" / "e2e-realpath.md"
    )
    assert args.report_json == str(
        benchmark_freshness_e2e.PROJECT_ROOT
        / ".artifacts"
        / "freshness"
        / "e2e-realpath-current.json"
    )
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "relative_path",
    [
        "docs/perf/freshness-e2e-realpath.md",
        "docs/archive/performance/freshness-e2e-realpath-2026-07-09.md",
    ],
)
def test_tracked_s8_freshness_docs_cannot_be_overwritten(relative_path):
    with pytest.raises(ValueError, match=r"\.artifacts/freshness"):
        benchmark_freshness_e2e.resolve_output_path(relative_path)


def test_main_rejects_tracked_output_before_runtime_access(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_freshness_e2e.py",
            "--report-md",
            "docs/perf/freshness-e2e-realpath.md",
        ],
    )

    def fail_if_runtime_is_touched(*_args, **_kwargs):
        raise AssertionError("runtime access must follow output validation")

    monkeypatch.setattr(benchmark_freshness_e2e, "read_metric", fail_if_runtime_is_touched)

    assert benchmark_freshness_e2e.main() == 2
    assert ".artifacts/freshness" in capsys.readouterr().err


def test_runtime_markdown_names_artifact_and_promotion_boundary():
    report = {
        "summary": {
            "samples": 1,
            "misses": 0,
            "p50_ms": 100.0,
            "p95_ms": 100.0,
            "p99_ms": 100.0,
            "min_ms": 100.0,
            "max_ms": 100.0,
            "mean_ms": 100.0,
        },
        "path": "orders.raw -> API",
        "generated": "2026-07-09T15:33:39.729745+00:00",
        "system": {"platform": "test", "python": "3.13.7"},
        "bootstrap": "127.0.0.1:19092",
        "api_base": "http://127.0.0.1:8000",
        "metric": "revenue",
        "window": "24h",
        "source_topic": "orders.raw",
        "poll_interval_ms": 50,
        "timeout_seconds": 90.0,
        "warmup": 2,
        "iterations": 1,
        "samples_ms": [100.0],
    }

    markdown = benchmark_freshness_e2e.build_markdown(report)

    assert "runtime artifact" in markdown.lower()
    assert ".artifacts/freshness/e2e-realpath.md" in markdown
    assert ".artifacts/freshness/e2e-realpath-current.json" in markdown
    assert "date-stamped" in markdown
    assert "single-node" in markdown
    assert "not a production" in markdown.lower()


def test_s8_freshness_docs_name_owner_and_snapshot_lifecycle():
    current = " ".join(
        (ROOT / "docs" / "perf" / "freshness-e2e-realpath.md").read_text(encoding="utf-8").split()
    )
    archived = " ".join(
        (ROOT / "docs" / "archive" / "performance" / "freshness-e2e-realpath-2026-07-09.md")
        .read_text(encoding="utf-8")
        .split()
    )
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "S8 real-path freshness artifact lifecycle" in current
    assert "`python scripts/benchmark_freshness_e2e.py`" in current
    assert "`.artifacts/freshness/e2e-realpath.md`" in current
    assert "`.artifacts/freshness/e2e-realpath-current.json`" in current
    assert "archive/performance/freshness-e2e-realpath-2026-07-09.md" in current
    assert "Original path: *docs/perf/freshness-e2e-realpath.md*" in archived
    assert "Content type: historical generated S8 real-path freshness snapshot" in archived
    assert "Measured: `2026-07-09T15:33:39.729745+00:00`" in archived
    assert "S8 real-path freshness benchmark snapshot/lifecycle sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan


def test_archived_s8_freshness_body_preserves_the_original_git_blob():
    archived = (
        ROOT / "docs" / "archive" / "performance" / "freshness-e2e-realpath-2026-07-09.md"
    ).read_bytes()
    marker = b"<!-- ARCHIVE BODY START -->"
    _metadata, original_tail = archived.split(marker, maxsplit=1)
    original = original_tail.removeprefix(b"\n")
    git_blob = b"blob " + str(len(original)).encode("ascii") + b"\0" + original

    assert hashlib.sha1(git_blob, usedforsecurity=False).hexdigest() == ARCHIVED_S8_FRESHNESS_BLOB
