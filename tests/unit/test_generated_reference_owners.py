from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from scripts.check_generated_reference_owners import (
    OWNERSHIP_HEADING,
    OWNERSHIP_PAGE,
    RUNTIME_PREFIX,
    TABLE_COLUMNS,
    check_generated_reference_owners,
    find_check_generators,
    load_tracked_paths,
    main,
    parse_ownership_table,
    path_is_tracked,
    path_tokens,
)

ROOT = Path(__file__).resolve().parents[2]

GENERATOR_SOURCE = (
    "import argparse\n"
    "\n"
    "\n"
    "def build() -> argparse.ArgumentParser:\n"
    "    parser = argparse.ArgumentParser()\n"
    '    parser.add_argument("--check", action="store_true")\n'
    "    return parser\n"
)
PLAIN_SOURCE = 'MESSAGE = "run the exporter with --check before review"\n'
GATE_SOURCE = 'RUFF_ARGV = ("ruff", "format", "--check", ".")\n'

TRACKED_SAMPLE = frozenset(
    {
        "docs/a.md",
        "config/contracts/metric.revenue.v1.yaml",
        "scripts/gen.py",
    }
)


def _write(root: Path, relative: str, body: str) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def _page(rows: Iterable[str]) -> str:
    header = "| " + " | ".join(TABLE_COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in TABLE_COLUMNS) + " |"
    return "\n".join(["# Documentation", "", OWNERSHIP_HEADING, "", header, separator, *rows, ""])


def _row(family: str, outputs: str, write: str, drift: str, lifecycle: str = "Notes") -> str:
    return f"| {family} | {outputs} | {write} | {drift} | {lifecycle} |"


def _problem(family: str, tail: str) -> str:
    return f'{OWNERSHIP_PAGE}: row "{family}": {tail}'


def test_real_ownership_table_matches_the_tree() -> None:
    assert check_generated_reference_owners(ROOT) == []
    tracked = load_tracked_paths(ROOT)
    assert tracked is not None
    rows = parse_ownership_table((ROOT / OWNERSHIP_PAGE).read_text(encoding="utf-8"))
    assert len(rows) >= 23
    generators = find_check_generators(ROOT, tracked)
    assert len(generators) >= 4
    assert "scripts/generate_contracts.py" in generators
    assert "scripts/golden_soak/architecture_gate.py" not in generators
    owned = {token for row in rows for cell in row.cells for token in path_tokens(cell)}
    assert "scripts/generate_contracts.py" in owned


def test_real_table_header_and_families_are_unique() -> None:
    rows = parse_ownership_table((ROOT / OWNERSHIP_PAGE).read_text(encoding="utf-8"))
    families = [row.family for row in rows]
    assert len(families) == len(set(families))
    assert all(len(row.cells) == len(TABLE_COLUMNS) for row in rows)


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("`python scripts/export_openapi.py --check`", {"scripts/export_openapi.py"}),
        (
            "`python -m scripts.run_nl_sql_eval` writes `.artifacts/nl-sql-eval/current.md`",
            {"scripts/run_nl_sql_eval.py", ".artifacts/nl-sql-eval/current.md"},
        ),
        (
            "`python tests/load/run_load_test.py` writes `.artifacts/load/results`",
            {"tests/load/run_load_test.py", ".artifacts/load/results"},
        ),
        ("destinations under `docs/` are rejected before mutmut runs", {"docs/"}),
        (
            "the six `config/contracts/metric.*.v1.yaml` files",
            {"config/contracts/metric.*.v1.yaml"},
        ),
        ("`make trivy-policy` and the tracked `.bandit-baseline.json`", set()),
        ("Runtime evidence review, not byte drift", set()),
    ],
)
def test_path_tokens_maps_backticked_tokens(cell: str, expected: set[str]) -> None:
    assert path_tokens(cell) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("docs/a.md", True),
        ("docs/b.md", False),
        ("docs/", True),
        ("tests/", False),
        ("config/contracts/metric.*.v1.yaml", True),
        ("config/contracts/order.*.yaml", False),
    ],
)
def test_path_is_tracked_truth_table(token: str, expected: bool) -> None:
    assert path_is_tracked(token, TRACKED_SAMPLE) is expected


def test_parse_ownership_table_requires_the_heading() -> None:
    with pytest.raises(ValueError):
        parse_ownership_table("# Documentation\n\n| Family | Tracked outputs |\n")


def test_parse_ownership_table_rejects_a_wrong_header() -> None:
    text = (
        f"{OWNERSHIP_HEADING}\n\n| Family | Outputs | Write | Drift check | Lifecycle |\n"
        "| --- | --- | --- | --- | --- |\n| Widgets | a | b | c | d |\n"
    )
    with pytest.raises(ValueError):
        parse_ownership_table(text)


def test_parse_ownership_table_stops_at_the_next_heading() -> None:
    text = _page([_row("Widgets", "`docs/widget.md`", "`python scripts/gen.py`", "Runtime review")])
    text += "\n## Sources of truth\n\n| Other | Table |\n| --- | --- |\n| a | b |\n"
    rows = parse_ownership_table(text)
    assert [row.family for row in rows] == ["Widgets"]
    assert rows[0].cells[TABLE_COLUMNS.index("Tracked outputs")] == "`docs/widget.md`"


def test_missing_table_is_the_only_problem(tmp_path: Path) -> None:
    _write(tmp_path, OWNERSHIP_PAGE, "# Documentation\n\nNo ownership table here.\n")
    _write(tmp_path, "scripts/gen.py", GENERATOR_SOURCE)
    tracked = {OWNERSHIP_PAGE, "scripts/gen.py"}
    assert check_generated_reference_owners(tmp_path, tracked_paths=tracked) == [
        f"{OWNERSHIP_PAGE}: generated-reference ownership table is missing or malformed"
    ]


def test_untracked_path_token_is_reported(tmp_path: Path) -> None:
    row = _row("Widgets", "`docs/widget.md`", "`python scripts/gen.py`", "Runtime review")
    _write(tmp_path, OWNERSHIP_PAGE, _page([row]))
    _write(tmp_path, "scripts/gen.py", GENERATOR_SOURCE)
    tracked = {OWNERSHIP_PAGE, "scripts/gen.py"}
    assert check_generated_reference_owners(tmp_path, tracked_paths=tracked) == [
        _problem("Widgets", "docs/widget.md is not tracked")
    ]


def test_tracked_runtime_artifact_is_reported(tmp_path: Path) -> None:
    runtime = f"{RUNTIME_PREFIX}widget/out.json"
    row = _row(
        "Widgets",
        "None; ignored runtime only",
        f"`python scripts/gen.py` writes `{runtime}`",
        "Runtime evidence review, not byte drift",
    )
    _write(tmp_path, OWNERSHIP_PAGE, _page([row]))
    _write(tmp_path, "scripts/gen.py", PLAIN_SOURCE)
    _write(tmp_path, runtime, "{}\n")
    tracked = {OWNERSHIP_PAGE, "scripts/gen.py", runtime}
    assert check_generated_reference_owners(tmp_path, tracked_paths=tracked) == [
        _problem("Widgets", f"{runtime} is a runtime artifact but is tracked")
    ]


def test_drift_check_without_tracked_output_is_reported(tmp_path: Path) -> None:
    row = _row(
        "Widgets",
        "None; ignored runtime only",
        "`python scripts/gen.py`",
        "`python scripts/gen.py --check`",
    )
    _write(tmp_path, OWNERSHIP_PAGE, _page([row]))
    _write(tmp_path, "scripts/gen.py", GENERATOR_SOURCE)
    tracked = {OWNERSHIP_PAGE, "scripts/gen.py"}
    assert check_generated_reference_owners(tmp_path, tracked_paths=tracked) == [
        _problem("Widgets", "drift check uses --check but lists no tracked output")
    ]


def test_generator_without_a_row_is_reported(tmp_path: Path) -> None:
    row = _row(
        "Widgets",
        "`docs/widget.md`",
        "`python scripts/gen.py`",
        "`python scripts/gen.py --check`",
    )
    _write(tmp_path, OWNERSHIP_PAGE, _page([row]))
    _write(tmp_path, "docs/widget.md", "# Widget\n")
    _write(tmp_path, "scripts/gen.py", GENERATOR_SOURCE)
    _write(tmp_path, "scripts/orphan_gen.py", GENERATOR_SOURCE)
    tracked = {OWNERSHIP_PAGE, "docs/widget.md", "scripts/gen.py", "scripts/orphan_gen.py"}
    assert check_generated_reference_owners(tmp_path, tracked_paths=tracked) == [
        "scripts/orphan_gen.py: declares --check but has no row in the "
        "generated-reference ownership table"
    ]


def test_check_string_outside_add_argument_is_not_a_generator(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/gate.py", GATE_SOURCE)
    _write(tmp_path, "scripts/gen.py", GENERATOR_SOURCE)
    _write(tmp_path, "scripts/notes.md", '`add_argument("--check")`\n')
    tracked = {"scripts/gate.py", "scripts/gen.py", "scripts/notes.md"}
    assert find_check_generators(tmp_path, tracked) == {"scripts/gen.py"}


def test_directory_and_glob_tokens_resolve_against_the_inventory(tmp_path: Path) -> None:
    row = _row(
        "Contracts",
        "`config/contracts/metric.*.v1.yaml`",
        "`python scripts/gen.py`",
        "`python scripts/gen.py --check`",
        "Generated from the models under `src/`",
    )
    _write(tmp_path, OWNERSHIP_PAGE, _page([row]))
    _write(tmp_path, "scripts/gen.py", GENERATOR_SOURCE)
    tracked = {
        OWNERSHIP_PAGE,
        "scripts/gen.py",
        "config/contracts/metric.revenue.v1.yaml",
        "src/agentflow_runtime/__init__.py",
    }
    assert check_generated_reference_owners(tmp_path, tracked_paths=tracked) == []


def test_main_passing_fixture_prints_ok(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(
        "Widgets",
        "`docs/widget.md`",
        "`python scripts/gen.py`",
        "`python scripts/gen.py --check`",
    )
    _write(tmp_path, OWNERSHIP_PAGE, _page([row]))
    _write(tmp_path, "docs/widget.md", "# Widget\n")
    _write(tmp_path, "scripts/gen.py", GENERATOR_SOURCE)
    monkeypatch.setattr(
        "scripts.check_generated_reference_owners.load_tracked_paths",
        lambda root: {OWNERSHIP_PAGE, "docs/widget.md", "scripts/gen.py"},
    )
    assert main(["--root", str(tmp_path)]) == 0
    assert (
        capsys.readouterr().out
        == "generated-reference owners: OK (1 families, 1 --check generators)\n"
    )


def test_main_failing_fixture_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row("Widgets", "`docs/widget.md`", "`python scripts/gen.py`", "Runtime review")
    _write(tmp_path, OWNERSHIP_PAGE, _page([row]))
    _write(tmp_path, "scripts/gen.py", GENERATOR_SOURCE)
    monkeypatch.setattr(
        "scripts.check_generated_reference_owners.load_tracked_paths",
        lambda root: {OWNERSHIP_PAGE, "scripts/gen.py"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert _problem("Widgets", "docs/widget.md is not tracked") in output
    assert "generated-reference owners: OK" not in output


def test_main_empty_table_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, OWNERSHIP_PAGE, _page([]))
    _write(tmp_path, "scripts/gen.py", GENERATOR_SOURCE)
    monkeypatch.setattr(
        "scripts.check_generated_reference_owners.load_tracked_paths",
        lambda root: {OWNERSHIP_PAGE, "scripts/gen.py"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    assert "generated-reference owners: OK" not in capsys.readouterr().out


def test_main_without_check_generators_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row("Widgets", "`docs/widget.md`", "`python scripts/gen.py`", "Runtime review")
    _write(tmp_path, OWNERSHIP_PAGE, _page([row]))
    _write(tmp_path, "docs/widget.md", "# Widget\n")
    _write(tmp_path, "scripts/gen.py", PLAIN_SOURCE)
    monkeypatch.setattr(
        "scripts.check_generated_reference_owners.load_tracked_paths",
        lambda root: {OWNERSHIP_PAGE, "docs/widget.md", "scripts/gen.py"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    assert "generated-reference owners: OK" not in capsys.readouterr().out


def test_main_without_git_inventory_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.check_generated_reference_owners.load_tracked_paths",
        lambda root: None,
    )
    assert main(["--root", str(tmp_path)]) == 1
    assert "git ls-files inventory unavailable" in capsys.readouterr().out
