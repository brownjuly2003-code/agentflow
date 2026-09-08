from __future__ import annotations

from pathlib import Path

import pytest
from markdown.extensions.toc import slugify, unique

from scripts.check_docs_anchors import (
    anchor_links,
    check_docs_anchors,
    heading_ids,
    is_living_page,
    load_tracked_paths,
    main,
)

ROOT = Path(__file__).resolve().parents[2]

REPLACEMENT_PROBLEM = "docs/bad.md:1: replacement character U+FFFD"
UTF8_PROBLEM = "docs/bad.md: not valid UTF-8"
NO_PAGE_PROBLEM = "docs/page.md:1: broken anchor 'docs/missing.md#hello' (no such page)"
NO_HEADING_PROBLEM = "docs/page.md:1: broken anchor 'docs/page.md#missing' (no such heading)"


def _write(root: Path, relative: str, body: str) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def test_real_docs_tree_has_no_anchor_or_replacement_problems() -> None:
    assert check_docs_anchors(ROOT) == []
    tracked = load_tracked_paths(ROOT)
    assert tracked is not None
    markdown_files = [path for path in tracked if path.endswith(".md")]
    assert len(markdown_files) >= 150
    links: list[tuple[int, str, str]] = []
    for relative in tracked:
        if not is_living_page(relative):
            continue
        path = ROOT.joinpath(*relative.split("/"))
        if not path.is_file():
            continue
        links.extend(anchor_links(relative, path.read_text(encoding="utf-8")))
    assert len(links) >= 25


def test_heading_ids_keeps_underscores_in_api_path() -> None:
    assert heading_ids("### GET /v1/entity/{entity_type}/{entity_id}") == {
        "get-v1entityentity_typeentity_id"
    }


def test_heading_ids_suffixes_duplicate_headings() -> None:
    assert heading_ids("# x\n# x\n") == {"x", "x_1"}


def test_heading_ids_cyrillic_matches_imported_slugify_unique() -> None:
    seen: set[str] = set()
    expected = unique(slugify("Назначение", "-"), seen)
    assert heading_ids("# Назначение\n") == {expected}


def test_heading_ids_skips_fenced_blocks() -> None:
    text = "```\n# inside-ticks\n```\n~~~\n# inside-tildes\n~~~\n# outside\n"
    assert heading_ids(text) == {"outside"}


def test_heading_ids_strips_code_spans_and_bold() -> None:
    assert heading_ids("# Use `code` and **bold**\n") == {"use-code-and-bold"}


def test_heading_ids_honours_attr_list_custom_id() -> None:
    assert heading_ids("# Title {#custom}\n") == {"custom"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/architecture.md", True),
        ("docs/README.md", True),
        ("docs/perf/x.md", False),
        ("README.md", False),
        ("docs/x.txt", False),
    ],
)
def test_is_living_page_truth_table(path: str, expected: bool) -> None:
    assert is_living_page(path) is expected


def test_anchor_links_resolves_same_page_relative_and_skips_non_md() -> None:
    source = "docs/api/index.md"
    text = (
        "See [local](#intro) and [ref](../api-reference.md#get-v1entityentity_typeentity_id).\n"
        "Skip [url](https://example.com/x.md#frag) and [mail](mailto:ops@example.com#x).\n"
        "Skip [code](../../src/foo/manager.py#L12).\n"
    )
    assert anchor_links(source, text) == [
        (1, "docs/api/index.md", "intro"),
        (1, "docs/api-reference.md", "get-v1entityentity_typeentity_id"),
    ]


def test_replacement_character_is_reported_with_exact_string(tmp_path: Path) -> None:
    _write(tmp_path, "docs/bad.md", "# Hello \ufffd\n")
    assert check_docs_anchors(tmp_path, tracked_paths={"docs/bad.md"}) == [REPLACEMENT_PROBLEM]


def test_invalid_utf8_is_reported_with_exact_string(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "bad.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"# \xff\n")
    assert check_docs_anchors(tmp_path, tracked_paths={"docs/bad.md"}) == [UTF8_PROBLEM]


def test_broken_anchor_missing_page_is_reported_with_exact_string(tmp_path: Path) -> None:
    _write(tmp_path, "docs/page.md", "See [gone](missing.md#hello).\n")
    assert check_docs_anchors(tmp_path, tracked_paths={"docs/page.md"}) == [NO_PAGE_PROBLEM]


def test_broken_anchor_missing_heading_is_reported_with_exact_string(tmp_path: Path) -> None:
    _write(tmp_path, "docs/page.md", "See [gone](page.md#missing).\n")
    assert check_docs_anchors(tmp_path, tracked_paths={"docs/page.md"}) == [NO_HEADING_PROBLEM]


def test_broken_anchor_from_historical_page_is_not_reported(tmp_path: Path) -> None:
    _write(tmp_path, "docs/page.md", "# Hello\n\nSee [ok](#hello).\n")
    _write(tmp_path, "docs/perf/snap.md", "See [broken](#nope) and [gone](../gone.md#x).\n")
    tracked = {"docs/page.md", "docs/perf/snap.md"}
    assert check_docs_anchors(tmp_path, tracked_paths=tracked) == []


def test_main_passing_fixture_prints_ok(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/page.md", "# Hello\n\nSee [ok](#hello).\n")
    monkeypatch.setattr(
        "scripts.check_docs_anchors.load_tracked_paths",
        lambda root: {"docs/page.md"},
    )
    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "docs anchors: OK (1 anchor links, 1 Markdown files)\n"


def test_main_failing_fixture_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/page.md", "See [gone](page.md#missing).\n")
    monkeypatch.setattr(
        "scripts.check_docs_anchors.load_tracked_paths",
        lambda root: {"docs/page.md"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert NO_HEADING_PROBLEM in output
    assert "docs anchors: OK" not in output


def test_main_no_anchor_links_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/page.md", "# Hello\n")
    monkeypatch.setattr(
        "scripts.check_docs_anchors.load_tracked_paths",
        lambda root: {"docs/page.md"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    assert "docs anchors: OK" not in capsys.readouterr().out
