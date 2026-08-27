from __future__ import annotations

from pathlib import Path

from scripts.check_docs_root_placement import (
    ROOT_MARKDOWN_ALLOWLIST,
    check_root_markdown_placement,
    load_tracked_paths,
)

ROOT = Path(__file__).resolve().parents[2]


def test_tracked_root_markdown_matches_the_allowlist() -> None:
    tracked = load_tracked_paths(ROOT)

    assert tracked is not None
    assert check_root_markdown_placement(tracked) == []


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
