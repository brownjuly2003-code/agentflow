from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import pytest

from scripts import plot_perf_history, record_perf_history

ROOT = Path(__file__).resolve().parents[2]
ARCHIVED_PERF_HISTORY_BLOB = "8ba12095aa0aefe43cff2cb78ecb9cbbb22edb65"


def test_record_defaults_to_ignored_runtime_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["record_perf_history.py"])

    args = record_perf_history.parse_args()

    assert args.history == ROOT / ".artifacts" / "perf-history" / "history.json"
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "relative_path",
    [
        ".github/perf-history.json",
        "docs/archive/performance/perf-history-2026-04-27.json",
    ],
)
def test_record_refuses_to_overwrite_tracked_history(relative_path: str) -> None:
    with pytest.raises(ValueError, match=r"\.artifacts/perf-history"):
        record_perf_history.resolve_history_path(relative_path)


def test_record_resolves_relative_history_from_project_root() -> None:
    expected = ROOT / ".artifacts" / "perf-history" / "custom.json"

    assert (
        record_perf_history.resolve_history_path(".artifacts/perf-history/custom.json") == expected
    )


def test_record_main_rejects_tracked_history_before_reading_results(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        record_perf_history,
        "parse_args",
        lambda: argparse.Namespace(
            results=ROOT / "missing-results.json",
            history=Path(".github/perf-history.json"),
            commit_sha="deadbeef",
            branch="main",
            max_entries=500,
        ),
    )

    assert record_perf_history.main() == 2
    assert ".artifacts/perf-history" in capsys.readouterr().err


def test_plot_defaults_to_ignored_runtime_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["plot_perf_history.py"])

    args = plot_perf_history.parse_args()

    expected_dir = ROOT / ".artifacts" / "perf-history"
    assert args.history == expected_dir / "history.json"
    assert args.output == expected_dir


@pytest.mark.parametrize("relative_dir", ["docs/perf", "docs/archive/performance"])
def test_plot_refuses_documentation_output(relative_dir: str) -> None:
    with pytest.raises(ValueError, match=r"\.artifacts/perf-history"):
        plot_perf_history.resolve_output_dir(relative_dir)


def test_plot_main_rejects_docs_output_before_loading_history(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        plot_perf_history,
        "parse_args",
        lambda: argparse.Namespace(
            history=ROOT / "missing-history.json",
            output=Path("docs/perf"),
        ),
    )
    monkeypatch.setattr(
        plot_perf_history,
        "load_history",
        lambda _path: pytest.fail("history must not be loaded for a protected output"),
    )

    assert plot_perf_history.main() == 2
    assert ".artifacts/perf-history" in capsys.readouterr().err


def test_archived_history_preserves_the_original_git_blob() -> None:
    archived = (
        ROOT / "docs" / "archive" / "performance" / "perf-history-2026-04-27.json"
    ).read_bytes()
    git_blob = b"blob " + str(len(archived)).encode("ascii") + b"\0" + archived

    assert hashlib.sha1(git_blob, usedforsecurity=False).hexdigest() == ARCHIVED_PERF_HISTORY_BLOB


def test_current_docs_name_history_owner_and_snapshot_lifecycle() -> None:
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    perf_hub = " ".join((ROOT / "docs" / "perf" / "README.md").read_text(encoding="utf-8").split())
    archive_hub = " ".join(
        (ROOT / "docs" / "archive" / "performance" / "README.md")
        .read_text(encoding="utf-8")
        .split()
    )
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())
    load_workflow = (ROOT / ".github" / "workflows" / "load-test.yml").read_text(encoding="utf-8")

    for current_doc in (readme, docs_hub, perf_hub, contributing):
        assert ".artifacts/perf-history/history.json" in current_doc
    assert "Performance history artifact lifecycle" in perf_hub
    assert "perf-history-2026-04-27.json" in perf_hub
    assert "perf-history-2026-04-27.json" in archive_hub
    assert "branch protection" in perf_hub.lower()
    assert "cross-run" in perf_hub.lower()
    assert "python scripts/record_perf_history.py" in contributing
    assert "python scripts/plot_perf_history.py" in contributing
    assert "--output docs/perf/" not in makefile
    assert "Performance-history runtime artifact sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan
    assert ".github/perf-history.json" not in load_workflow
