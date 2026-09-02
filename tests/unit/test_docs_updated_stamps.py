from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from scripts.check_docs_updated_stamps import (
    CANONICAL_STAMP,
    DATED_PAGES,
    STAMP_LINE,
    canonical_stamp_date,
    check_docs_updated_stamps,
    is_living_page,
    load_tracked_paths,
    main,
    stamp_lines,
)

ROOT = Path(__file__).resolve().parents[2]

UNDATED_PROBLEM = (
    "docs/hub.md:3: 'Updated' stamp on an undated living page "
    "(remove it or add the page to DATED_PAGES)"
)
UNTRACKED_PROBLEM = "docs/dated.md: dated page is not tracked"
MISSING_PROBLEM = (
    "docs/dated.md: dated page has no '**Updated:** YYYY-MM-DD' stamp "
    "before the first section heading"
)
MALFORMED_PROBLEM = (
    "docs/dated.md:3: malformed 'Updated' stamp (expected '**Updated:** YYYY-MM-DD')"
)
DUPLICATE_PROBLEM = "docs/dated.md:5: duplicate 'Updated' stamp"


def _write(root: Path, relative: str, body: str) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def _use_dated_pages(monkeypatch: pytest.MonkeyPatch, *pages: str) -> None:
    monkeypatch.setattr("scripts.check_docs_updated_stamps.DATED_PAGES", frozenset(pages))


def test_real_docs_tree_has_no_updated_stamp_problems() -> None:
    assert check_docs_updated_stamps(ROOT) == []
    tracked = load_tracked_paths(ROOT)
    assert tracked is not None
    living = [path for path in tracked if is_living_page(path)]
    assert len(living) >= 55
    # The allowlist is the contract: a new dated page is a deliberate edit here.
    assert len(DATED_PAGES) == 7
    assert DATED_PAGES <= set(tracked)
    for page in sorted(DATED_PAGES):
        assert is_living_page(page)


@pytest.mark.parametrize(
    "line",
    [
        "> Updated: 2026-08-26. This page is the navigation hub for the complete",
        "> Updated: **2026-08-26**. The golden topology remains a production candidate, not",
        "**Last updated:** 2026-05-24",
        "**Last updated:** 2026-08-30 (API/Flink image-policy gate)",
        "**Updated:** 2026-08-27",
    ],
)
def test_stamp_line_matches_every_stamp_form(line: str) -> None:
    assert STAMP_LINE.match(line) is not None


@pytest.mark.parametrize(
    "line",
    [
        "**Date:** 2026-04-25 (updated 2026-05-24 for cross-link)",
        "updated with the new measurement and rationale.",
        "**Repository snapshot reviewed:** 2026-04-18",
    ],
)
def test_stamp_line_ignores_prose_and_other_metadata(line: str) -> None:
    assert STAMP_LINE.match(line) is None


def test_stamp_lines_skips_fenced_blocks_and_numbers_from_one() -> None:
    text = "# Title\n\n```markdown\n**Updated:** 2026-01-01\n```\n\n**Updated:** 2026-02-02\n"
    assert stamp_lines(text) == [(7, "**Updated:** 2026-02-02")]


def test_canonical_stamp_accepts_a_bare_date_and_a_short_note() -> None:
    assert CANONICAL_STAMP.match("**Updated:** 2026-08-27") is not None
    assert canonical_stamp_date("**Updated:** 2026-08-27") == datetime.date(2026, 8, 27)
    noted = "**Updated:** 2026-08-30 (API/Flink image-policy gate)"
    assert CANONICAL_STAMP.match(noted) is not None
    assert canonical_stamp_date(noted) == datetime.date(2026, 8, 30)


def test_canonical_stamp_rejects_legacy_forms_and_impossible_dates() -> None:
    assert CANONICAL_STAMP.match("**Last updated:** 2026-05-24") is None
    assert canonical_stamp_date("**Last updated:** 2026-05-24") is None
    assert CANONICAL_STAMP.match("> Updated: 2026-08-26.") is None
    assert canonical_stamp_date("> Updated: 2026-08-26.") is None
    # CANONICAL_STAMP pins only the shape; the calendar check rejects month 13.
    assert CANONICAL_STAMP.match("**Updated:** 2026-13-01") is not None
    assert canonical_stamp_date("**Updated:** 2026-13-01") is None


def test_undated_living_page_with_a_stamp_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/hub.md", "# Hub\n\n> Updated: 2026-08-26. Navigation hub.\n")
    _use_dated_pages(monkeypatch)
    problems = check_docs_updated_stamps(tmp_path, tracked_paths={"docs/hub.md"})
    assert problems == [UNDATED_PROBLEM]


def test_undated_living_page_without_a_stamp_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/hub.md", "# Hub\n\nNavigation hub.\n")
    _use_dated_pages(monkeypatch)
    assert check_docs_updated_stamps(tmp_path, tracked_paths={"docs/hub.md"}) == []


def test_untracked_dated_page_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "docs/dated.md", "# Dated\n\n**Updated:** 2026-08-27\n\n## Section\n")
    _use_dated_pages(monkeypatch, "docs/dated.md")
    problems = check_docs_updated_stamps(tmp_path, tracked_paths={"docs/hub.md"})
    assert problems == [UNTRACKED_PROBLEM]


def test_dated_page_without_a_stamp_before_the_first_heading_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/dated.md", "# Dated\n\nPurpose.\n\n## Section\n\nBody.\n")
    _use_dated_pages(monkeypatch, "docs/dated.md")
    problems = check_docs_updated_stamps(tmp_path, tracked_paths={"docs/dated.md"})
    assert problems == [MISSING_PROBLEM]


def test_dated_page_with_a_legacy_stamp_is_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/dated.md", "# Dated\n\n**Last updated:** 2026-05-24\n\n## Section\n")
    _use_dated_pages(monkeypatch, "docs/dated.md")
    problems = check_docs_updated_stamps(tmp_path, tracked_paths={"docs/dated.md"})
    assert problems == [MALFORMED_PROBLEM]


def test_dated_page_with_a_future_stamp_is_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/dated.md", "# Dated\n\n**Updated:** 2999-01-01\n\n## Section\n")
    _use_dated_pages(monkeypatch, "docs/dated.md")
    problems = check_docs_updated_stamps(tmp_path, tracked_paths={"docs/dated.md"})
    assert problems == [MALFORMED_PROBLEM]


def test_dated_page_with_two_stamps_reports_the_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        "docs/dated.md",
        "# Dated\n\n**Updated:** 2026-08-27\n\n**Updated:** 2026-08-26\n\n## Section\n",
    )
    _use_dated_pages(monkeypatch, "docs/dated.md")
    problems = check_docs_updated_stamps(tmp_path, tracked_paths={"docs/dated.md"})
    assert problems == [DUPLICATE_PROBLEM]


def test_historical_page_with_a_legacy_stamp_is_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/perf/snap.md", "# Snapshot\n\n**Last updated:** 2026-05-24\n")
    _use_dated_pages(monkeypatch)
    assert check_docs_updated_stamps(tmp_path, tracked_paths={"docs/perf/snap.md"}) == []


def test_main_passing_fixture_prints_ok(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/dated.md", "# Dated\n\n**Updated:** 2026-08-27\n\n## Section\n")
    _write(tmp_path, "docs/hub.md", "# Hub\n\nNavigation hub.\n")
    _use_dated_pages(monkeypatch, "docs/dated.md")
    monkeypatch.setattr(
        "scripts.check_docs_updated_stamps.load_tracked_paths",
        lambda root: {"docs/dated.md", "docs/hub.md"},
    )
    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "docs updated stamps: OK (1 dated pages, 2 living pages)\n"


def test_main_failing_fixture_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/hub.md", "# Hub\n\n**Last updated:** 2026-05-24\n")
    _use_dated_pages(monkeypatch)
    monkeypatch.setattr(
        "scripts.check_docs_updated_stamps.load_tracked_paths",
        lambda root: {"docs/hub.md"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "docs/hub.md:3: 'Updated' stamp on an undated living page" in output
    assert "docs updated stamps: OK" not in output


def test_main_no_living_pages_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "README.md", "# Root\n")
    _use_dated_pages(monkeypatch)
    monkeypatch.setattr(
        "scripts.check_docs_updated_stamps.load_tracked_paths",
        lambda root: {"README.md"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    assert "docs updated stamps: FAIL (0 living pages)" in capsys.readouterr().out
