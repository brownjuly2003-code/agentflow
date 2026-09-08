"""Fail closed when an ``Updated`` stamp sits on the wrong living docs page.

A stamp is only worth reading when the date is part of the claim: a status
snapshot, an audit result, a rehearsal or resume boundary, a record carrying a
superseded notice. Everywhere else the date decays silently — a hub edited
today still shows last quarter's stamp — so a living page that is not on the
``DATED_PAGES`` allowlist must carry no stamp at all and let Git history be the
date.

A living page is a tracked ``docs/**/*.md`` file that is not under
``HISTORICAL_DIRECTORIES``; hubs are living pages here. Historical pages are
out of scope: ``scripts/check_historical_claims.py`` already bans ``updated:``
under ``docs/archive``, ``docs/decisions``, ``docs/evidence``,
``docs/migration`` and ``docs/perf``, and the two checkers must not overlap.

``STAMP_LINE`` deliberately matches every stamp *shape* ever used in this tree
(``> Updated: <date>.``, ``> Updated: **<date>**.``, ``**Updated:** <date>``,
``**Last updated:** <date>``) so a legacy form on an undated page is caught,
and it deliberately does not match ``**Date:** 2026-04-25 (updated ...)`` or
prose containing the word "updated". Stamps inside fenced code blocks are
documentation *about* stamps and are ignored.
"""

from __future__ import annotations

import argparse
import datetime
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

# Living pages whose date is part of the claim the reader must trust. Every
# other living page is undated by policy; see the "Documentation Conventions"
# section of docs/engineering-standards.md.
DATED_PAGES = frozenset(
    {
        "docs/STATUS.md",
        "docs/operations/api-duckdb-non-target-scratch-rehearsal-runbook.md",
        "docs/operations/api-duckdb-persistence-recovery-design.md",
        "docs/operations/chaos-runbook.md",
        "docs/operations/ci-soak-compose-foundation.md",
        "docs/operations/ci-soak-next-session-runbook.md",
        "docs/security-audit.md",
    }
)

STAMP_LINE = re.compile(r"^\s*(?:>\s*)?\**(?:last[ -])?updated\**\s*:", re.IGNORECASE)
CANONICAL_STAMP = re.compile(r"^\*\*Updated:\*\* (\d{4}-\d{2}-\d{2})(?: \S.*)?$")
SECTION_HEADING = re.compile(r"^#{2,6}\s")
OPEN_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")

INVENTORY_PROBLEM = "docs updated stamps: git ls-files inventory unavailable"


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


def stamp_lines(text: str) -> list[tuple[int, str]]:
    """Return ``(1-based line number, line)`` for every stamp outside a fence."""

    return [(number, line) for number, line in _iter_unfenced_lines(text) if STAMP_LINE.match(line)]


def _first_section_heading(text: str) -> int | None:
    for number, line in _iter_unfenced_lines(text):
        if SECTION_HEADING.match(line):
            return number
    return None


def canonical_stamp_date(line: str) -> datetime.date | None:
    """Return the stamp date when *line* is a canonical, real, non-future stamp."""

    match = CANONICAL_STAMP.match(line)
    if match is None:
        return None
    try:
        stamped = datetime.date.fromisoformat(match.group(1))
    except ValueError:
        return None
    if stamped > datetime.date.today():
        return None
    return stamped


def _undated_problems(relative: str, text: str) -> list[str]:
    return [
        f"{relative}:{number}: 'Updated' stamp on an undated living page "
        "(remove it or add the page to DATED_PAGES)"
        for number, _ in stamp_lines(text)
    ]


def _dated_problems(relative: str, text: str) -> list[str]:
    problems: list[str] = []
    stamps = stamp_lines(text)
    heading = _first_section_heading(text)
    leading = [stamp for stamp in stamps if heading is None or stamp[0] < heading]
    if not leading:
        problems.append(
            f"{relative}: dated page has no '**Updated:** YYYY-MM-DD' stamp "
            "before the first section heading"
        )
    else:
        number, line = leading[0]
        if canonical_stamp_date(line) is None:
            problems.append(
                f"{relative}:{number}: malformed 'Updated' stamp "
                "(expected '**Updated:** YYYY-MM-DD')"
            )
    problems.extend(f"{relative}:{number}: duplicate 'Updated' stamp" for number, _ in stamps[1:])
    return problems


def check_docs_updated_stamps(root: Path, tracked_paths: Iterable[str] | None = None) -> list[str]:
    """Report ``Updated``-stamp policy violations on living docs pages, sorted."""

    if tracked_paths is None:
        loaded = load_tracked_paths(root)
        if loaded is None:
            return [INVENTORY_PROBLEM]
        inventory = loaded
    else:
        inventory = {path.replace("\\", "/") for path in tracked_paths}

    dated = set(DATED_PAGES)
    problems = [f"{relative}: dated page is not tracked" for relative in dated - inventory]
    for relative in inventory:
        if not is_living_page(relative):
            continue
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        if relative in dated:
            problems.extend(_dated_problems(relative, text))
        else:
            problems.extend(_undated_problems(relative, text))
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracked = load_tracked_paths(root)
    if tracked is None:
        print("docs updated stamps: FAIL")
        print(INVENTORY_PROBLEM)
        return 1

    problems = check_docs_updated_stamps(root, tracked_paths=tracked)
    if problems:
        for problem in problems:
            print(problem)
        return 1

    living = sum(1 for path in tracked if is_living_page(path))
    if living == 0:
        print("docs updated stamps: FAIL (0 living pages)")
        return 1

    print(f"docs updated stamps: OK ({len(DATED_PAGES)} dated pages, {living} living pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
