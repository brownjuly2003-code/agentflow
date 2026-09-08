"""Fail closed when the generated-reference ownership table drifts from the tree.

``docs/README.md`` declares exactly one writer per generated family in its
``## Generated-reference ownership`` table
(``Family | Tracked outputs | Write | Drift check | Lifecycle``). That table is
the canonical-owner contract, and nothing else pins it: a generator can gain or
lose a ``--check`` mode, a tracked output can be renamed, or a replaceable
runtime path can leak into Git without the table noticing.

This ratchet re-derives the contract from the repository:

* every backticked token in any of the five cells that looks like a repository
  path (``PATH_PREFIXES``) must name something Git tracks, unless it is a
  ``.artifacts/`` runtime path, which must *not* be tracked;
* a row whose ``Drift check`` cell runs ``--check`` must list at least one
  tracked output, because byte drift needs a committed byte to compare against;
* every tracked ``scripts/**/*.py`` that declares ``--check`` through
  ``argparse`` must appear in some row, so no generator is unowned.

``CHECK_FLAG_DECLARATION`` anchors on ``add_argument(`` on purpose:
``scripts/golden_soak/architecture_gate.py`` carries the bare string
``"--check"`` inside ruff and git argv tuples and is not a generator.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

OWNERSHIP_PAGE = "docs/README.md"
OWNERSHIP_HEADING = "## Generated-reference ownership"
TABLE_COLUMNS = ("Family", "Tracked outputs", "Write", "Drift check", "Lifecycle")
RUNTIME_PREFIX = ".artifacts/"
PATH_PREFIXES = (
    "docs/",
    "scripts/",
    "tests/",
    "config/",
    "src/",
    "sdk/",
    ".github/",
    ".artifacts/",
)
GENERATOR_PREFIX = "scripts/"
CHECK_FLAG_DECLARATION = re.compile(r'add_argument\(\s*"--check"')

BACKTICKED = re.compile(r"`([^`]+)`")
SEPARATOR_CELL = re.compile(r":?-{3,}:?")
MODULE_FLAG = "-m"
PUNCTUATION_STRIP = ",;"

MALFORMED_PROBLEM = f"{OWNERSHIP_PAGE}: generated-reference ownership table is missing or malformed"
INVENTORY_PROBLEM = "generated-reference owners: git ls-files inventory unavailable"


@dataclass(frozen=True)
class OwnershipRow:
    """One family row of the generated-reference ownership table."""

    family: str
    cells: tuple[str, ...]


def load_tracked_paths(root: Path) -> set[str] | None:
    """Return Git-tracked paths, or ``None`` when the inventory is unavailable."""

    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "-z"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    if listed.returncode != 0:
        return None
    return {
        raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for raw in listed.stdout.split(b"\0")
        if raw
    }


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return len(cells) == len(TABLE_COLUMNS) and all(
        SEPARATOR_CELL.fullmatch(cell) for cell in cells
    )


def parse_ownership_table(text: str) -> list[OwnershipRow]:
    """Return the family rows of the ownership table declared in *text*.

    The table is the Markdown table under ``OWNERSHIP_HEADING`` up to the next
    ``"## "`` heading. ``ValueError`` is raised when the heading is missing or
    the table is not well formed: no header row, a header that differs from
    ``TABLE_COLUMNS``, a missing separator row, or a data row whose cell count
    differs from the header. A well-formed table with no data rows returns an
    empty list; ``main`` treats that as a rotted ratchet.
    """

    lines = text.splitlines()
    heading_index = next(
        (index for index, line in enumerate(lines) if line.strip() == OWNERSHIP_HEADING),
        None,
    )
    if heading_index is None:
        raise ValueError(f"{OWNERSHIP_PAGE}: heading {OWNERSHIP_HEADING!r} not found")

    end = len(lines)
    for index in range(heading_index + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break

    block = (line.strip() for line in lines[heading_index + 1 : end])
    table = [line for line in block if line.startswith("|")]
    if len(table) < 2:
        raise ValueError(f"{OWNERSHIP_PAGE}: ownership table has no header and separator rows")
    if tuple(_split_row(table[0])) != TABLE_COLUMNS:
        raise ValueError(f"{OWNERSHIP_PAGE}: ownership table header is not {TABLE_COLUMNS}")
    if not _is_separator(_split_row(table[1])):
        raise ValueError(f"{OWNERSHIP_PAGE}: ownership table has no separator row")

    rows: list[OwnershipRow] = []
    for line in table[2:]:
        cells = _split_row(line)
        if len(cells) != len(TABLE_COLUMNS):
            raise ValueError(f"{OWNERSHIP_PAGE}: ownership row has {len(cells)} cells")
        rows.append(OwnershipRow(family=cells[0], cells=tuple(cells)))
    return rows


def path_tokens(cell: str) -> set[str]:
    """Return repository paths named by the backticked tokens of *cell*.

    Every backticked token is split on whitespace. A word that starts with a
    ``PATH_PREFIXES`` prefix is a path (so command tokens such as ``python
    scripts/x.py --check`` contribute ``scripts/x.py``), and ``-m <module>``
    contributes the module's source path (``python -m scripts.run_nl_sql_eval``
    contributes ``scripts/run_nl_sql_eval.py``). Everything else — prose,
    flags, ``make`` targets, root-level file names — is ignored.
    """

    found: set[str] = set()
    for token in BACKTICKED.findall(cell):
        words = token.split()
        for index, word in enumerate(words):
            if word == MODULE_FLAG and index + 1 < len(words):
                module = words[index + 1].strip(PUNCTUATION_STRIP)
                candidate = f"{module.replace('.', '/')}.py"
                if candidate.startswith(PATH_PREFIXES):
                    found.add(candidate)
                continue
            candidate = word.strip(PUNCTUATION_STRIP)
            if candidate.startswith(PATH_PREFIXES):
                found.add(candidate)
    return found


def path_is_tracked(token: str, tracked_paths: Iterable[str]) -> bool:
    """Return whether *token* names at least one tracked path.

    An exact path matches itself, a token ending in ``/`` matches any tracked
    path under that directory, and a token containing ``*`` matches through
    ``fnmatch`` against the inventory.
    """

    inventory = {path.replace("\\", "/") for path in tracked_paths}
    if token in inventory:
        return True
    if token.endswith("/"):
        return any(path.startswith(token) for path in inventory)
    if "*" in token:
        return any(fnmatch.fnmatch(path, token) for path in inventory)
    return False


def find_check_generators(root: Path, tracked_paths: Iterable[str]) -> set[str]:
    """Return tracked ``scripts/**/*.py`` files that declare ``--check`` via argparse."""

    generators: set[str] = set()
    for path in tracked_paths:
        relative = path.replace("\\", "/")
        if not relative.startswith(GENERATOR_PREFIX) or not relative.endswith(".py"):
            continue
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file():
            continue
        if CHECK_FLAG_DECLARATION.search(target.read_text(encoding="utf-8")):
            generators.add(relative)
    return generators


def check_generated_reference_owners(
    root: Path, tracked_paths: Iterable[str] | None = None
) -> list[str]:
    """Report every disagreement between the ownership table and the tracked tree."""

    if tracked_paths is None:
        loaded = load_tracked_paths(root)
        if loaded is None:
            return [INVENTORY_PROBLEM]
        inventory = loaded
    else:
        inventory = {path.replace("\\", "/") for path in tracked_paths}

    page = root.joinpath(*PurePosixPath(OWNERSHIP_PAGE).parts)
    try:
        rows = parse_ownership_table(page.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [MALFORMED_PROBLEM]

    outputs_index = TABLE_COLUMNS.index("Tracked outputs")
    drift_index = TABLE_COLUMNS.index("Drift check")

    problems: list[str] = []
    owned: set[str] = set()
    for row in rows:
        tokens: set[str] = set()
        for cell in row.cells:
            tokens |= path_tokens(cell)
        owned |= tokens
        for token in sorted(tokens):
            tracked = path_is_tracked(token, inventory)
            if token.startswith(RUNTIME_PREFIX):
                if tracked:
                    problems.append(
                        f'{OWNERSHIP_PAGE}: row "{row.family}": '
                        f"{token} is a runtime artifact but is tracked"
                    )
            elif not tracked:
                problems.append(f'{OWNERSHIP_PAGE}: row "{row.family}": {token} is not tracked')
        if "--check" in row.cells[drift_index] and not path_tokens(row.cells[outputs_index]):
            problems.append(
                f'{OWNERSHIP_PAGE}: row "{row.family}": '
                "drift check uses --check but lists no tracked output"
            )

    for generator in find_check_generators(root, inventory):
        if generator not in owned:
            problems.append(
                f"{generator}: declares --check but has no row in the "
                "generated-reference ownership table"
            )
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracked = load_tracked_paths(root)
    if tracked is None:
        print("generated-reference owners: FAIL")
        print("git ls-files inventory unavailable")
        return 1

    problems = check_generated_reference_owners(root, tracked_paths=tracked)
    page = root.joinpath(*PurePosixPath(OWNERSHIP_PAGE).parts)
    try:
        rows = parse_ownership_table(page.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    generators = find_check_generators(root, tracked)

    if not rows:
        print("generated-reference owners: FAIL (0 families)")
        for problem in problems:
            print(problem)
        return 1
    if not generators:
        print("generated-reference owners: FAIL (0 --check generators)")
        for problem in problems:
            print(problem)
        return 1
    if problems:
        for problem in problems:
            print(problem)
        return 1

    print(
        f"generated-reference owners: OK ({len(rows)} families, "
        f"{len(generators)} --check generators)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
