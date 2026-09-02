from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_docs_page_openings import (
    PENDING_OPERATOR_PAGES,
    check_docs_page_openings,
    is_living_page,
    is_operator_page,
    load_tracked_paths,
    main,
    opening_lines,
)

ROOT = Path(__file__).resolve().parents[2]

NOT_H1_PROBLEM = "docs/hub.md:1: first content line is not an H1 heading"
ZERO_H1_PROBLEM = "docs/hub.md: 0 H1 headings outside fenced blocks (expected 1)"
TWO_H1_PROBLEM = "docs/hub.md: 2 H1 headings outside fenced blocks (expected 1)"
PURPOSE_PROBLEM = "docs/hub.md: no purpose paragraph between the H1 and the first section heading"
NO_AUDIENCE_PROBLEM = (
    "docs/operations/page.md: operator page has no '**Audience:**' line "
    "before the first section heading"
)
NO_PREREQUISITES_PROBLEM = (
    "docs/operations/page.md: operator page has no '**Prerequisites:**' line "
    "before the first section heading"
)
DUPLICATE_AUDIENCE_PROBLEM = "docs/operations/page.md:7: duplicate '**Audience:**' line"
DUPLICATE_PREREQUISITES_PROBLEM = "docs/operations/page.md:11: duplicate '**Prerequisites:**' line"
ORDER_PROBLEM = (
    "docs/operations/page.md:5: '**Audience:**' line must come before '**Prerequisites:**'"
)
PENDING_BOTH_PROBLEM = (
    "docs/operations/page.md: pending operator page already carries both lines "
    "(remove it from PENDING_OPERATOR_PAGES)"
)
UNTRACKED_PENDING_PROBLEM = "docs/operations/page.md: pending operator page is not tracked"
NOT_OPERATOR_PENDING_PROBLEM = "docs/product.md: pending operator page is not an operator page"


def _write(root: Path, relative: str, body: str) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def _use_pending(monkeypatch: pytest.MonkeyPatch, *pages: str) -> None:
    monkeypatch.setattr(
        "scripts.check_docs_page_openings.PENDING_OPERATOR_PAGES",
        frozenset(pages),
    )


def _compliant_hub() -> str:
    return "# Hub\n\nNavigation hub for living pages.\n\n## Section\n"


def _compliant_operator() -> str:
    return (
        "# Operator page\n\n"
        "This page owns one operator procedure.\n\n"
        "**Audience:** on-call operator\n\n"
        "**Prerequisites:** kubectl and Grafana\n\n"
        "## Symptom\n"
    )


def test_real_docs_tree_has_no_page_opening_problems() -> None:
    assert check_docs_page_openings(ROOT) == []
    tracked = load_tracked_paths(ROOT)
    assert tracked is not None
    living = [path for path in tracked if is_living_page(path)]
    operator = [path for path in living if is_operator_page(path)]
    assert len(living) >= 61
    assert len(operator) == 25
    assert len(PENDING_OPERATOR_PAGES) == 14
    assert PENDING_OPERATOR_PAGES <= set(tracked)
    for page in sorted(PENDING_OPERATOR_PAGES):
        assert is_operator_page(page)
        assert is_living_page(page)


def test_real_docs_tree_main_prints_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out.strip()
    assert output.startswith("docs page openings: OK (")
    living_part, operator_part, pending_part = (
        output.removeprefix("docs page openings: OK (").removesuffix(")").split(", ")
    )
    living = int(living_part.split()[0])
    pending = int(pending_part.split()[0])
    assert living >= 61
    assert operator_part == "25 operator pages"
    assert pending == 14


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/architecture.md", True),
        ("docs/README.md", True),
        ("docs/operations/README.md", True),
        ("docs/runbook.md", True),
        ("docs/perf/x.md", False),
        ("docs/archive/x.md", False),
        ("docs/dv2-multi-branch/architecture.md", False),
        ("README.md", False),
        ("docs/x.txt", False),
    ],
)
def test_is_living_page_truth_table(path: str, expected: bool) -> None:
    assert is_living_page(path) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/runbook.md", True),
        ("docs/operations/codecov-setup.md", True),
        ("docs/runbooks/cdc-lag.md", True),
        ("docs/operations/README.md", False),
        ("docs/runbooks/README.md", False),
        ("docs/README.md", False),
        ("docs/product.md", False),
        ("docs/archive/operations/x.md", False),
        ("docs/perf/x.md", False),
    ],
)
def test_is_operator_page_truth_table(path: str, expected: bool) -> None:
    assert is_operator_page(path) is expected


def test_fenced_backtick_heading_is_not_an_h1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        "docs/hub.md",
        "# Hub\n\nPurpose paragraph.\n\n```bash\n# not a heading\n```\n\n## Section\n",
    )
    _use_pending(monkeypatch)
    assert check_docs_page_openings(tmp_path, tracked_paths={"docs/hub.md"}) == []


def test_fenced_tilde_heading_is_not_an_h1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(
        tmp_path,
        "docs/hub.md",
        "# Hub\n\nPurpose paragraph.\n\n~~~\n# not a heading\n~~~\n\n## Section\n",
    )
    _use_pending(monkeypatch)
    assert check_docs_page_openings(tmp_path, tracked_paths={"docs/hub.md"}) == []


def test_opening_lines_stop_at_the_first_section_heading() -> None:
    text = "# Title\n\nPurpose.\n\n**Audience:** ops\n\n## Section\n\n**Prerequisites:** x\n"
    lines = [line for _, line in opening_lines(text)]
    assert "Purpose." in lines
    assert "**Audience:** ops" in lines
    assert "**Prerequisites:** x" not in lines
    assert "## Section" not in lines


def test_first_content_line_is_not_an_h1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "docs/hub.md", "Not a heading\n\n# Hub\n\nPurpose paragraph.\n")
    _use_pending(monkeypatch)
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/hub.md"})
    assert NOT_H1_PROBLEM in problems


def test_zero_h1_headings_are_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "docs/hub.md", "Purpose paragraph.\n\n## Section\n")
    _use_pending(monkeypatch)
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/hub.md"})
    assert ZERO_H1_PROBLEM in problems
    assert NOT_H1_PROBLEM in problems


def test_two_unfenced_h1_headings_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        "docs/hub.md",
        "# Hub\n\nPurpose paragraph.\n\n# Another\n\n## Section\n",
    )
    _use_pending(monkeypatch)
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/hub.md"})
    assert problems == [TWO_H1_PROBLEM]


def test_stamp_only_opening_has_no_purpose_paragraph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/hub.md", "# Hub\n\n**Updated:** 2026-08-31\n\n## Purpose\n")
    _use_pending(monkeypatch)
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/hub.md"})
    assert problems == [PURPOSE_PROBLEM]


def test_pending_operator_page_may_lack_a_purpose_paragraph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        "docs/operations/page.md",
        "# Operator\n\n**Updated:** 2026-08-31\n\n## Purpose\n\nLater.\n",
    )
    _use_pending(monkeypatch, "docs/operations/page.md")
    assert check_docs_page_openings(tmp_path, tracked_paths={"docs/operations/page.md"}) == []


def test_operator_page_missing_audience_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        "docs/operations/page.md",
        "# Operator\n\nPurpose.\n\n**Prerequisites:** kubectl\n\n## Section\n",
    )
    _use_pending(monkeypatch)
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/operations/page.md"})
    assert problems == [NO_AUDIENCE_PROBLEM]


def test_operator_page_missing_prerequisites_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        "docs/operations/page.md",
        "# Operator\n\nPurpose.\n\n**Audience:** on-call\n\n## Section\n",
    )
    _use_pending(monkeypatch)
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/operations/page.md"})
    assert problems == [NO_PREREQUISITES_PROBLEM]


def test_duplicate_audience_and_prerequisites_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        "docs/operations/page.md",
        "# Operator\n\n"
        "Purpose.\n\n"
        "**Audience:** a\n\n"
        "**Audience:** b\n\n"
        "**Prerequisites:** c\n\n"
        "**Prerequisites:** d\n\n"
        "## Section\n",
    )
    _use_pending(monkeypatch)
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/operations/page.md"})
    assert problems == [DUPLICATE_PREREQUISITES_PROBLEM, DUPLICATE_AUDIENCE_PROBLEM]


def test_audience_must_come_before_prerequisites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        tmp_path,
        "docs/operations/page.md",
        "# Operator\n\nPurpose.\n\n**Prerequisites:** kubectl\n\n**Audience:** on-call\n\n## Section\n",
    )
    _use_pending(monkeypatch)
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/operations/page.md"})
    assert problems == [ORDER_PROBLEM]


def test_pending_page_that_already_carries_both_lines_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/operations/page.md", _compliant_operator())
    _use_pending(monkeypatch, "docs/operations/page.md")
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/operations/page.md"})
    assert problems == [PENDING_BOTH_PROBLEM]


def test_untracked_pending_page_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/hub.md", _compliant_hub())
    _use_pending(monkeypatch, "docs/operations/page.md")
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/hub.md"})
    assert problems == [UNTRACKED_PENDING_PROBLEM]


def test_pending_page_that_is_not_an_operator_page_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "docs/product.md", _compliant_hub())
    _use_pending(monkeypatch, "docs/product.md")
    problems = check_docs_page_openings(tmp_path, tracked_paths={"docs/product.md"})
    assert problems == [NOT_OPERATOR_PENDING_PROBLEM]


def test_historical_page_is_not_checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "docs/perf/snap.md", "no heading\n")
    _use_pending(monkeypatch)
    assert check_docs_page_openings(tmp_path, tracked_paths={"docs/perf/snap.md"}) == []


def test_compliant_operator_page_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "docs/operations/page.md", _compliant_operator())
    _use_pending(monkeypatch)
    assert check_docs_page_openings(tmp_path, tracked_paths={"docs/operations/page.md"}) == []


def test_main_passing_fixture_prints_ok(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/hub.md", _compliant_hub())
    _use_pending(monkeypatch)
    monkeypatch.setattr(
        "scripts.check_docs_page_openings.load_tracked_paths",
        lambda root: {"docs/hub.md"},
    )
    assert main(["--root", str(tmp_path)]) == 0
    assert (
        capsys.readouterr().out
        == "docs page openings: OK (1 living pages, 0 operator pages, 0 pending)\n"
    )


def test_main_failing_fixture_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/hub.md", "Not a heading\n")
    _use_pending(monkeypatch)
    monkeypatch.setattr(
        "scripts.check_docs_page_openings.load_tracked_paths",
        lambda root: {"docs/hub.md"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "first content line is not an H1 heading" in output
    assert "docs page openings: OK" not in output


def test_main_no_living_pages_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "README.md", "# Root\n")
    _use_pending(monkeypatch)
    monkeypatch.setattr(
        "scripts.check_docs_page_openings.load_tracked_paths",
        lambda root: {"README.md"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out == "docs page openings: no living pages found\n"
