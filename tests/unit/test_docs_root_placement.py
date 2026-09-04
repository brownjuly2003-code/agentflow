from __future__ import annotations

from pathlib import Path

from scripts.check_docs_root_placement import (
    REPO_ROOT_MARKDOWN_ALLOWLIST,
    ROOT_MARKDOWN_ALLOWLIST,
    check_repo_root_markdown_placement,
    check_root_markdown_placement,
    load_tracked_paths,
    main,
)

ROOT = Path(__file__).resolve().parents[2]


def test_completed_documentation_plan_is_not_a_repo_root_entrypoint() -> None:
    assert "plan_26_08_2026.md" not in REPO_ROOT_MARKDOWN_ALLOWLIST


def test_tracked_root_markdown_matches_the_allowlist() -> None:
    tracked = load_tracked_paths(ROOT)

    assert tracked is not None
    assert check_root_markdown_placement(tracked) == []
    assert check_repo_root_markdown_placement(tracked) == []


def test_unexpected_tracked_root_markdown_is_rejected() -> None:
    tracked = set(ROOT_MARKDOWN_ALLOWLIST)
    tracked.update({"README.md", "docs/perf/nested-report.md", "docs/new-report.md"})

    assert check_root_markdown_placement(tracked) == [
        "unexpected tracked root Markdown: docs/new-report.md"
    ]


def test_missing_allowed_root_markdown_is_rejected() -> None:
    tracked = set(ROOT_MARKDOWN_ALLOWLIST) - {"docs/README.md"}

    assert check_root_markdown_placement(tracked) == [
        "missing allowed root Markdown: docs/README.md"
    ]


def test_unexpected_tracked_repo_root_markdown_is_rejected() -> None:
    tracked = set(REPO_ROOT_MARKDOWN_ALLOWLIST)
    tracked.add("notes.md")

    assert check_repo_root_markdown_placement(tracked) == [
        "unexpected tracked repository-root Markdown: notes.md"
    ]


def test_missing_allowed_repo_root_markdown_is_rejected() -> None:
    tracked = set(REPO_ROOT_MARKDOWN_ALLOWLIST) - {"README.md"}

    assert check_repo_root_markdown_placement(tracked) == [
        "missing allowed repository-root Markdown: README.md"
    ]


def test_tracked_repo_root_markdown_absent_from_working_tree_is_still_rejected(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    tracked = set(ROOT_MARKDOWN_ALLOWLIST) | set(REPO_ROOT_MARKDOWN_ALLOWLIST)
    tracked.add("notes.md")
    monkeypatch.setattr(
        "scripts.check_docs_root_placement.load_tracked_paths",
        lambda root: tracked,
    )

    assert not (tmp_path / "notes.md").exists()
    assert main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "unexpected tracked repository-root Markdown: notes.md" in captured.out
