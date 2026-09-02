from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_historical_claims import (
    CLAIM_OWNERS,
    FORBIDDEN_PHRASES,
    HISTORICAL_DIRECTORIES,
    LIVING_INDEX_PAGES,
    check_historical_claims,
    find_claims,
    is_historical_page,
    load_tracked_paths,
    main,
)

ROOT = Path(__file__).resolve().parents[2]

OWNED_BY_STATUS = tuple(phrase for phrase in FORBIDDEN_PHRASES if phrase != "production-accepted")


def _write(root: Path, relative: str, body: str) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def _problem(relative: str, line: int, phrase: str) -> str:
    return f'{relative}:{line}: living-status phrase "{phrase}" belongs to docs/STATUS.md'


def test_real_historical_tree_has_no_living_claims() -> None:
    assert check_historical_claims(ROOT) == []
    tracked = load_tracked_paths(ROOT)
    assert tracked is not None
    pages = [path for path in tracked if is_historical_page(path)]
    assert len(pages) >= 90


def test_public_constants_describe_the_real_tree() -> None:
    tracked = load_tracked_paths(ROOT)
    assert tracked is not None
    for directory in HISTORICAL_DIRECTORIES:
        assert (ROOT / directory).is_dir()
    for owner in CLAIM_OWNERS:
        assert owner in tracked
    for page in LIVING_INDEX_PAGES:
        assert page in tracked


@pytest.mark.parametrize("phrase", OWNED_BY_STATUS)
def test_forbidden_phrases_are_living_status_vocabulary(phrase: str) -> None:
    status = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8").lower()
    assert phrase in status


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/perf/x-2026-01-01.md", True),
        ("docs/decisions/0013-golden-production-topology.md", True),
        ("docs/archive/release-history-v1-v2.md", True),
        ("docs/archive/README.md", False),
        ("docs/archive/product/README.md", False),
        ("docs/evidence/INDEX.md", False),
        ("docs/STATUS.md", False),
        ("docs/perf/notes.txt", False),
    ],
)
def test_is_historical_page_truth_table(path: str, expected: bool) -> None:
    assert is_historical_page(path) is expected


def test_find_claims_reports_line_numbers_and_mixed_case() -> None:
    text = "# Title\n> Updated: **2026-08-26**\nbody\nPRODUCTION ACCEPTED build\n"
    assert find_claims(text) == [(2, "updated:"), (4, "production accepted")]


def test_find_claims_reports_every_phrase_on_one_line() -> None:
    assert find_claims("the release line is a closure candidate\n") == [
        (1, "closure candidate"),
        (1, "release line"),
    ]


def test_find_claims_ignores_legitimate_historical_wording() -> None:
    text = "This snapshot is not production acceptance.\nIt records a production candidate build.\n"
    assert find_claims(text) == []


@pytest.mark.parametrize("phrase", FORBIDDEN_PHRASES)
def test_single_phrase_in_a_historical_page_is_reported(tmp_path: Path, phrase: str) -> None:
    relative = "docs/perf/latency-2026-01-01.md"
    _write(tmp_path, relative, f"# Snapshot\n\nThe {phrase} note.\n")
    assert check_historical_claims(tmp_path, tracked_paths={relative}) == [
        _problem(relative, 3, phrase)
    ]


def test_problems_are_sorted_across_pages(tmp_path: Path) -> None:
    first = "docs/archive/a-2026-01-01.md"
    second = "docs/perf/b-2026-01-02.md"
    _write(tmp_path, first, "# A\n\nrelease line\n")
    _write(tmp_path, second, "Updated: today\n")
    assert check_historical_claims(tmp_path, tracked_paths={second, first}) == [
        _problem(first, 3, "release line"),
        _problem(second, 1, "updated:"),
    ]


def test_index_readme_and_living_owner_pages_are_ignored(tmp_path: Path) -> None:
    readme = "docs/archive/README.md"
    nested = "docs/archive/product/README.md"
    index = "docs/evidence/INDEX.md"
    owner = "docs/STATUS.md"
    body = "".join(f"{phrase}\n" for phrase in FORBIDDEN_PHRASES)
    for relative in (readme, nested, index, owner):
        _write(tmp_path, relative, body)
    assert check_historical_claims(tmp_path, tracked_paths={readme, nested, index, owner}) == []


def test_main_passing_fixture_prints_ok(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative = "docs/perf/clean-2026-01-01.md"
    _write(tmp_path, relative, "# Clean snapshot\n\nMeasured on 2026-01-01.\n")
    monkeypatch.setattr(
        "scripts.check_historical_claims.load_tracked_paths",
        lambda root: {relative},
    )
    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "historical claims: OK (1 historical pages)\n"


def test_main_failing_fixture_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative = "docs/decisions/0099-bad.md"
    _write(tmp_path, relative, "# Decision\n\nUpdated: 2026-09-01\n")
    monkeypatch.setattr(
        "scripts.check_historical_claims.load_tracked_paths",
        lambda root: {relative},
    )
    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert _problem(relative, 3, "updated:") in output
    assert "historical claims: OK" not in output


def test_main_empty_tree_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/archive/README.md", "# Index\n")
    monkeypatch.setattr(
        "scripts.check_historical_claims.load_tracked_paths",
        lambda root: {"docs/archive/README.md"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    assert "historical claims: OK" not in capsys.readouterr().out


def test_main_without_git_inventory_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.check_historical_claims.load_tracked_paths",
        lambda root: None,
    )
    assert main(["--root", str(tmp_path)]) == 1
    assert "git ls-files inventory unavailable" in capsys.readouterr().out
