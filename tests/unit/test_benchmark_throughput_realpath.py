from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from scripts import benchmark_throughput_realpath

ROOT = Path(__file__).resolve().parents[2]
ARCHIVED_THROUGHPUT_BASELINE_BLOB = "146a67379bc643b9f2207fc2f3a9c0cda7c9c635"


def test_default_markdown_is_an_ignored_runtime_artifact() -> None:
    assert benchmark_throughput_realpath.DEFAULT_REPORT == (
        benchmark_throughput_realpath.PROJECT_ROOT
        / ".artifacts"
        / "throughput"
        / "realpath-current.md"
    )
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "relative_path",
    [
        "docs/perf/throughput-realpath.md",
        "docs/archive/performance/throughput-realpath-2026-07-09.md",
    ],
)
def test_tracked_throughput_docs_cannot_be_overwritten(relative_path: str) -> None:
    with pytest.raises(ValueError, match=r"\.artifacts/throughput"):
        benchmark_throughput_realpath.resolve_report_path(relative_path)


@pytest.mark.parametrize("output_flag", ["--report-md", "--report-json"])
def test_main_rejects_tracked_report_before_runtime(monkeypatch, capsys, output_flag: str) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_throughput_realpath.py",
            output_flag,
            "docs/perf/throughput-realpath.md",
        ],
    )

    def fail_if_runtime_is_touched(_metrics_url: str) -> dict[str, float]:
        pytest.fail("tracked-output validation must run before bridge access")

    monkeypatch.setattr(
        benchmark_throughput_realpath,
        "read_bridge_snapshot",
        fail_if_runtime_is_touched,
    )

    assert benchmark_throughput_realpath.main() == 2
    assert ".artifacts/throughput" in capsys.readouterr().err


def test_throughput_docs_name_owner_and_snapshot_lifecycle() -> None:
    current = " ".join(
        (ROOT / "docs" / "perf" / "throughput-realpath.md").read_text(encoding="utf-8").split()
    )
    archived = " ".join(
        (ROOT / "docs" / "archive" / "performance" / "throughput-realpath-2026-07-09.md")
        .read_text(encoding="utf-8")
        .split()
    )
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "Real-path throughput benchmark artifact lifecycle" in current
    assert "`python scripts/benchmark_throughput_realpath.py`" in current
    assert "`.artifacts/throughput/realpath-current.md`" in current
    assert "`.artifacts/throughput/realpath-current.json`" in current
    assert "archive/performance/throughput-realpath-2026-07-09.md" in current
    assert "Original path: *docs/perf/throughput-realpath.md*" in archived
    assert "Content type: historical generated S10 throughput baseline snapshot" in archived
    assert "Measured: `2026-07-09T15:41:31+00:00`" in archived
    assert "| Real-path throughput benchmark |" in docs_hub
    assert ".artifacts/throughput/realpath-current.md" in docs_hub
    assert "python scripts/benchmark_throughput_realpath.py" in contributing
    assert ".artifacts/throughput/realpath-current.md" in contributing
    assert "Real-path throughput benchmark snapshot/lifecycle sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan


def test_archived_throughput_body_preserves_the_original_git_blob() -> None:
    archived = (
        ROOT / "docs" / "archive" / "performance" / "throughput-realpath-2026-07-09.md"
    ).read_bytes()
    marker = b"<!-- ARCHIVE BODY START -->"
    _metadata, original_tail = archived.split(marker, maxsplit=1)
    title = (
        b"# Real-path throughput (S10): Kafka \xe2\x86\x92 Flink "
        b"\xe2\x86\x92 bridge \xe2\x86\x92 ClickHouse"
    )
    original = title + original_tail
    git_blob = b"blob " + str(len(original)).encode("ascii") + b"\0" + original

    assert hashlib.sha1(git_blob, usedforsecurity=False).hexdigest() == (
        ARCHIVED_THROUGHPUT_BASELINE_BLOB
    )


def test_exact_catchup_completion_rejects_ninety_nine_percent() -> None:
    assert not benchmark_throughput_realpath.catchup_is_complete(
        processed=99.0,
        produced=100,
        lag=0.0,
        baseline_lag=0.0,
        pending_latency_count=0,
        completion_ratio=1.0,
    )
    assert benchmark_throughput_realpath.catchup_is_complete(
        processed=100.0,
        produced=100,
        lag=0.0,
        baseline_lag=0.0,
        pending_latency_count=0,
        completion_ratio=1.0,
    )
