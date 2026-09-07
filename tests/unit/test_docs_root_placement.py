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


def test_agents_md_is_a_member_of_the_repo_root_markdown_allowlist() -> None:
    assert "AGENTS.md" in REPO_ROOT_MARKDOWN_ALLOWLIST
    assert REPO_ROOT_MARKDOWN_ALLOWLIST == frozenset(
        {
            "README.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "AGENTS.md",
        }
    )


def test_check_repo_root_markdown_placement_accepts_tracked_agents_md() -> None:
    tracked = set(REPO_ROOT_MARKDOWN_ALLOWLIST) | {"AGENTS.md"}

    assert check_repo_root_markdown_placement(tracked) == []


def test_unlisted_repo_root_document_notes_md_is_still_rejected() -> None:
    tracked = set(REPO_ROOT_MARKDOWN_ALLOWLIST) | {"AGENTS.md", "NOTES.md"}

    assert check_repo_root_markdown_placement(tracked) == [
        "unexpected tracked repository-root Markdown: NOTES.md"
    ]


def test_existing_repo_root_markdown_entries_remain_accepted_and_required() -> None:
    existing = (
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
    )
    for name in existing:
        assert name in REPO_ROOT_MARKDOWN_ALLOWLIST
        tracked = set(REPO_ROOT_MARKDOWN_ALLOWLIST) - {name}
        assert check_repo_root_markdown_placement(tracked) == [
            f"missing allowed repository-root Markdown: {name}"
        ]

    assert check_repo_root_markdown_placement(set(REPO_ROOT_MARKDOWN_ALLOWLIST)) == []


def test_repo_root_markdown_allowlist_rejects_prefix_and_case_variants() -> None:
    tracked = set(REPO_ROOT_MARKDOWN_ALLOWLIST) | {"AGENTS.md", "AGENT.md", "agents.md"}
    problems = check_repo_root_markdown_placement(tracked)

    assert "unexpected tracked repository-root Markdown: AGENT.md" in problems
    assert "unexpected tracked repository-root Markdown: agents.md" in problems
    assert "unexpected tracked repository-root Markdown: AGENTS.md" not in problems


def test_main_accepts_the_real_tree_when_agents_md_is_tracked(monkeypatch, capsys) -> None:
    tracked = load_tracked_paths(ROOT)
    assert tracked is not None
    tracked = set(tracked)
    tracked.add("AGENTS.md")
    monkeypatch.setattr(
        "scripts.check_docs_root_placement.load_tracked_paths",
        lambda root: tracked,
    )

    assert main([]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("docs root placement: OK ")
