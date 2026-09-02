"""Fail closed when point-in-time pages restate living project status.

Current project truth — production status, the release line, the project
lifecycle, and the ``Updated:`` stamp — is owned by ``docs/STATUS.md``,
``docs/PROJECT_CLOSURE.md``, ``README.md`` and ``config/project_claims.toml``.
Pages under ``docs/archive``, ``docs/decisions``, ``docs/evidence``,
``docs/migration`` and ``docs/perf`` are immutable point-in-time records: they
may quote a dated fact, but they must never restate that living vocabulary in
their own voice, because nobody updates them when the truth moves. Every
tracked Markdown page under those directories is checked, except ``README.md``
index pages (matched by basename) and the living indexes in
``LIVING_INDEX_PAGES``.

Matching is a plain case-insensitive substring test per line: no regex, no word
boundaries, so what fails is exactly what a reader can grep. This module
deliberately does not import ``HISTORICAL_DIRECTORIES`` from
``scripts.check_docs_links``: that tuple serves link checking, covers
``docs/codex-tasks`` and omits ``docs/decisions`` and ``docs/archive``, so the
two scopes must stay independent.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

HISTORICAL_DIRECTORIES = (
    "docs/archive",
    "docs/decisions",
    "docs/evidence",
    "docs/migration",
    "docs/perf",
)

# Living pages that sit inside a historical directory. ``README.md`` index
# pages are exempt everywhere by basename and need no entry here.
LIVING_INDEX_PAGES = frozenset({"docs/evidence/INDEX.md"})

CLAIM_OWNERS = (
    "docs/STATUS.md",
    "docs/PROJECT_CLOSURE.md",
    "README.md",
    "config/project_claims.toml",
)

# Living-status vocabulary. Every entry except the hyphenated spelling of
# "production accepted" is present in docs/STATUS.md; the test pins that.
# Deliberately excluded: "production candidate" (a real dated verdict in
# docs/perf/checkpoint-restore-replay-2026-08-02.md) and "production
# acceptance" (used only inside disclaimers such as "is not production
# acceptance").
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "updated:",
    "production accepted",
    "production-accepted",
    "closure candidate",
    "release line",
)


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


def is_historical_page(path: str) -> bool:
    """Return whether *path* is a point-in-time page this ratchet owns."""

    relative = path.replace("\\", "/")
    if not relative.endswith(".md"):
        return False
    if relative in LIVING_INDEX_PAGES:
        return False
    posix = PurePosixPath(relative)
    if posix.name == "README.md":
        return False
    return any(
        directory == str(posix.parent) or str(posix.parent).startswith(f"{directory}/")
        for directory in HISTORICAL_DIRECTORIES
    )


def find_claims(text: str) -> list[tuple[int, str]]:
    """Return ``(1-based line number, phrase)`` for every living-status hit."""

    hits: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        hits.extend((number, phrase) for phrase in FORBIDDEN_PHRASES if phrase in lowered)
    return hits


def check_historical_claims(root: Path, tracked_paths: Iterable[str] | None = None) -> list[str]:
    """Report living-status vocabulary used by tracked historical pages."""

    if tracked_paths is None:
        loaded = load_tracked_paths(root)
        if loaded is None:
            return ["historical claims: git ls-files inventory unavailable"]
        inventory = loaded
    else:
        inventory = {path.replace("\\", "/") for path in tracked_paths}

    problems: list[str] = []
    for relative in inventory:
        if not is_historical_page(relative):
            continue
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file():
            continue
        for number, phrase in find_claims(target.read_text(encoding="utf-8")):
            problems.append(
                f'{relative}:{number}: living-status phrase "{phrase}" belongs to {CLAIM_OWNERS[0]}'
            )
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracked = load_tracked_paths(root)
    if tracked is None:
        print("historical claims: FAIL")
        print("git ls-files inventory unavailable")
        return 1

    problems = check_historical_claims(root, tracked_paths=tracked)
    pages = sum(1 for path in tracked if is_historical_page(path))
    if pages == 0:
        print("historical claims: FAIL (0 historical pages)")
        for problem in problems:
            print(problem)
        return 1
    if problems:
        for problem in problems:
            print(problem)
        return 1

    print(f"historical claims: OK ({pages} historical pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
