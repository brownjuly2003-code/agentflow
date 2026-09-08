"""Fail closed when a living docs page does not open as a reader would scan it.

A reader decides in the first screen whether the page is theirs. Every living
page must therefore open with exactly one H1 and a paragraph of purpose before
the first section heading. Operator and runbook pages then carry one
``**Audience:**`` line and one ``**Prerequisites:**`` line, Audience first.

A living page is a tracked ``docs/**/*.md`` file that is not under
``HISTORICAL_DIRECTORIES``; hubs are living pages here. An operator page is a
living page under ``docs/operations/`` or ``docs/runbooks/``, plus
``docs/runbook.md``, excluding hub ``README.md`` files. Headings and metadata
inside fenced code blocks are documentation *about* commands and are ignored.

``PENDING_OPERATOR_PAGES`` is the remaining content allowlist: those operator
pages do not yet carry both lines. The set only shrinks. A pending page that
gains both lines is reported until it is removed from the set.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

HISTORICAL_DIRECTORIES = (
    "docs/archive",
    "docs/decisions",
    "docs/dv2-multi-branch",
    "docs/evidence",
    "docs/migration",
    "docs/perf",
)

OPERATOR_PAGE_PREFIXES = ("docs/operations/", "docs/runbooks/")
OPERATOR_PAGES_EXTRA = frozenset({"docs/runbook.md"})

# Emptied on 2026-09-01; kept so a future operator page can be staged.
PENDING_OPERATOR_PAGES: frozenset[str] = frozenset()

H1 = re.compile(r"^#\s+\S")
SECTION_HEADING = re.compile(r"^#{2,6}\s")
OPEN_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
AUDIENCE_LINE = re.compile(r"^\*\*Audience:\*\* \S")
PREREQUISITES_LINE = re.compile(r"^\*\*Prerequisites:\*\* \S")
STAMP_LINE = re.compile(r"^\s*(?:>\s*)?\**(?:last[ -])?updated\**\s*:", re.IGNORECASE)

INVENTORY_PROBLEM = "docs page openings: git ls-files inventory unavailable"


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


def is_living_page(path: str) -> bool:
    """Return whether *path* is a living docs page this policy owns."""

    relative = path.replace("\\", "/")
    if not relative.endswith(".md"):
        return False
    posix = PurePosixPath(relative)
    try:
        posix.relative_to("docs")
    except ValueError:
        return False
    return not any(
        directory == str(posix.parent) or str(posix.parent).startswith(f"{directory}/")
        for directory in HISTORICAL_DIRECTORIES
    )


def is_operator_page(path: str) -> bool:
    """Return whether *path* is an operator or runbook page (hubs excluded)."""

    relative = path.replace("\\", "/")
    if PurePosixPath(relative).name == "README.md":
        return False
    if relative in OPERATOR_PAGES_EXTRA:
        return True
    return relative.startswith(OPERATOR_PAGE_PREFIXES)


def _iter_unfenced_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(1-based line number, line)`` for every line outside a fence."""

    fence_close: re.Pattern[str] | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if fence_close is None:
            match = OPEN_FENCE.match(line)
            if match is not None:
                marker, info = match.group(2), match.group(3)
                if marker[0] == "`" and "`" in info:
                    yield number, line
                    continue
                fence_close = re.compile(
                    rf"^( {{0,3}}){re.escape(marker[0])}{{{len(marker)},}}[ \t]*$"
                )
                continue
            yield number, line
            continue
        if fence_close.match(line):
            fence_close = None


def opening_lines(text: str) -> list[tuple[int, str]]:
    """Return unfenced lines after the H1 up to, but excluding, the first section."""

    seen_h1 = False
    found: list[tuple[int, str]] = []
    for number, line in _iter_unfenced_lines(text):
        if not seen_h1:
            if H1.match(line):
                seen_h1 = True
            continue
        if SECTION_HEADING.match(line):
            break
        found.append((number, line))
    return found


def _problem(relative: str, message: str, line: int | None = None) -> str:
    if line is None:
        return f"{relative}: {message}"
    return f"{relative}:{line}: {message}"


def _is_prose(line: str) -> bool:
    if not line.strip():
        return False
    if STAMP_LINE.match(line):
        return False
    if AUDIENCE_LINE.match(line):
        return False
    return PREREQUISITES_LINE.match(line) is None


def _first_nonblank_unfenced(text: str) -> tuple[int, str] | None:
    for number, line in _iter_unfenced_lines(text):
        if line.strip():
            return number, line
    return None


def _living_page_problems(relative: str, text: str, *, require_purpose: bool) -> list[str]:
    problems: list[str] = []
    first = _first_nonblank_unfenced(text)
    if first is None or H1.match(first[1]) is None:
        problems.append(
            _problem(
                relative,
                "first content line is not an H1 heading",
                None if first is None else first[0],
            )
        )
    h1s = [number for number, line in _iter_unfenced_lines(text) if H1.match(line)]
    if len(h1s) != 1:
        problems.append(
            _problem(
                relative,
                f"{len(h1s)} H1 headings outside fenced blocks (expected 1)",
            )
        )
    opening = opening_lines(text)
    if require_purpose and not any(_is_prose(line) for _, line in opening):
        problems.append(
            _problem(
                relative,
                "no purpose paragraph between the H1 and the first section heading",
            )
        )
    return problems


def _operator_opening_problems(relative: str, opening: list[tuple[int, str]]) -> list[str]:
    problems: list[str] = []
    audience = [(number, line) for number, line in opening if AUDIENCE_LINE.match(line)]
    prerequisites = [(number, line) for number, line in opening if PREREQUISITES_LINE.match(line)]
    if not audience:
        problems.append(
            _problem(
                relative,
                "operator page has no '**Audience:**' line before the first section heading",
            )
        )
    if not prerequisites:
        problems.append(
            _problem(
                relative,
                "operator page has no '**Prerequisites:**' line before the first section heading",
            )
        )
    problems.extend(
        _problem(relative, "duplicate '**Audience:**' line", number) for number, _ in audience[1:]
    )
    problems.extend(
        _problem(relative, "duplicate '**Prerequisites:**' line", number)
        for number, _ in prerequisites[1:]
    )
    if audience and prerequisites and prerequisites[0][0] < audience[0][0]:
        problems.append(
            _problem(
                relative,
                "'**Audience:**' line must come before '**Prerequisites:**'",
                prerequisites[0][0],
            )
        )
    return problems


def _pending_page_problems(relative: str, inventory: set[str], texts: dict[str, str]) -> list[str]:
    problems: list[str] = []
    if relative not in inventory:
        problems.append(_problem(relative, "pending operator page is not tracked"))
    if not is_operator_page(relative):
        problems.append(_problem(relative, "pending operator page is not an operator page"))
    text = texts.get(relative)
    if text is not None:
        opening = opening_lines(text)
        has_audience = any(AUDIENCE_LINE.match(line) for _, line in opening)
        has_prerequisites = any(PREREQUISITES_LINE.match(line) for _, line in opening)
        if has_audience and has_prerequisites:
            problems.append(
                _problem(
                    relative,
                    "pending operator page already carries both lines "
                    "(remove it from PENDING_OPERATOR_PAGES)",
                )
            )
    return problems


def check_docs_page_openings(root: Path, tracked_paths: Iterable[str] | None = None) -> list[str]:
    """Report page-opening policy violations on living docs pages, sorted."""

    if tracked_paths is None:
        loaded = load_tracked_paths(root)
        if loaded is None:
            return [INVENTORY_PROBLEM]
        inventory = loaded
    else:
        inventory = {path.replace("\\", "/") for path in tracked_paths}

    problems: list[str] = []
    texts: dict[str, str] = {}
    for relative in inventory:
        if not is_living_page(relative):
            continue
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file():
            continue
        try:
            texts[relative] = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(_problem(relative, "not valid UTF-8"))

    for relative, text in texts.items():
        pending_operator = is_operator_page(relative) and relative in PENDING_OPERATOR_PAGES
        problems.extend(_living_page_problems(relative, text, require_purpose=not pending_operator))
        if is_operator_page(relative) and relative not in PENDING_OPERATOR_PAGES:
            problems.extend(_operator_opening_problems(relative, opening_lines(text)))

    for relative in PENDING_OPERATOR_PAGES:
        problems.extend(_pending_page_problems(relative, inventory, texts))

    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracked = load_tracked_paths(root)
    if tracked is None:
        print(INVENTORY_PROBLEM)
        return 1

    problems = check_docs_page_openings(root, tracked_paths=tracked)
    if problems:
        for problem in problems:
            print(problem)
        return 1

    living = sum(1 for path in tracked if is_living_page(path))
    if living == 0:
        print("docs page openings: no living pages found")
        return 1

    operator = sum(1 for path in tracked if is_living_page(path) and is_operator_page(path))
    pending = len(PENDING_OPERATOR_PAGES)
    print(
        "docs page openings: OK "
        f"({living} living pages, {operator} operator pages, {pending} pending)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
