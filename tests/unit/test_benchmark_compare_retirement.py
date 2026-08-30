from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVED_BASELINE_BLOB = "ba43d81d20015121a2c0748b3fba95ae52ded374"


def test_legacy_benchmark_comparator_paths_are_retired() -> None:
    assert not (ROOT / "scripts" / "benchmark_compare.py").exists()
    assert not (ROOT / "docs" / "benchmarks" / "baseline.json").exists()
    assert (ROOT / "scripts" / "check_performance.py").is_file()
    assert (ROOT / "docs" / "benchmark-baseline.json").is_file()


def test_archived_comparator_baseline_preserves_the_original_git_blob() -> None:
    archived = (
        ROOT / "docs" / "archive" / "performance" / "benchmark-compare-baseline-2026-04-12.json"
    ).read_bytes()
    git_blob = b"blob " + str(len(archived)).encode("ascii") + b"\0" + archived

    assert hashlib.sha1(git_blob, usedforsecurity=False).hexdigest() == ARCHIVED_BASELINE_BLOB


def test_lifecycle_docs_name_the_canonical_gate_and_retired_snapshot() -> None:
    lifecycle = " ".join(
        (ROOT / "docs" / "perf" / "load-benchmark-latest.md").read_text(encoding="utf-8").split()
    )
    archive = " ".join(
        (ROOT / "docs" / "archive" / "performance" / "README.md")
        .read_text(encoding="utf-8")
        .split()
    )

    assert "scripts/check_performance.py" in lifecycle
    assert "docs/benchmark-baseline.json" in lifecycle
    assert "scripts/benchmark_compare.py" in lifecycle
    assert "benchmark-compare-baseline-2026-04-12.json" in archive
    assert ARCHIVED_BASELINE_BLOB in archive
