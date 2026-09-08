"""Fail closed when a living documentation page has no inbound link.

A living page is a tracked ``docs/**/*.md`` file that is not under
``HISTORICAL_DIRECTORIES`` and is not a hub in ``ENTRYPOINTS``. Hubs need no
inbound link. Every other living page must be reachable from some tracked
Markdown page in the repository or from a ``mkdocs.yml`` ``nav:`` entry.
Self-links never count. The required remediation is a hub link from
``docs/README.md`` or an archive move with provenance; this checker only
reports the gap.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable
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
ENTRYPOINTS = frozenset({"docs/README.md", "docs/index.md"})
INLINE_LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
NAV_MARKDOWN = re.compile(r":\s*['\"]?([^\s:#]+\.md)(?:#[^\s]*)?['\"]?\s*$", re.MULTILINE)
PROBLEM_SUFFIX = "no inbound link from any tracked Markdown page or mkdocs nav"


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
    """Return whether *path* is a living docs page that must have an inbound link."""

    relative = path.replace("\\", "/")
    if not relative.endswith(".md"):
        return False
    posix = PurePosixPath(relative)
    try:
        posix.relative_to("docs")
    except ValueError:
        return False
    if relative in ENTRYPOINTS:
        return False
    return not any(
        directory == str(posix.parent) or str(posix.parent).startswith(f"{directory}/")
        for directory in HISTORICAL_DIRECTORIES
    )


def _normalize_posix(path: str) -> str:
    parts: list[str] = []
    for part in PurePosixPath(path.replace("\\", "/")).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _resolve_target(source: str, raw: str) -> str | None:
    target = raw.strip().strip("<>")
    if not target or "://" in target or target.lower().startswith("mailto:"):
        return None
    target = target.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if not target:
        return None
    parent = PurePosixPath(source.replace("\\", "/")).parent
    combined = target if str(parent) == "." else f"{parent}/{target}"
    return _normalize_posix(combined)


def outbound_targets(source: str, text: str) -> set[str]:
    """Return repo-relative POSIX targets of inline and reference Markdown links."""

    found: set[str] = set()
    for match in INLINE_LINK.finditer(text):
        resolved = _resolve_target(source, match.group(1))
        if resolved:
            found.add(resolved)
    for match in REFERENCE_LINK.finditer(text):
        resolved = _resolve_target(source, match.group(1))
        if resolved:
            found.add(resolved)
    return found


def _mkdocs_nav_targets(text: str) -> set[str]:
    found: set[str] = set()
    for match in NAV_MARKDOWN.finditer(text):
        resolved = _resolve_target("docs/index.md", match.group(1))
        if resolved:
            found.add(resolved)
    return found


def inbound_index(root: Path, tracked_paths: Iterable[str]) -> dict[str, set[str]]:
    """Map each linked page to the tracked Markdown sources (and mkdocs nav) that name it."""

    inventory = {path.replace("\\", "/") for path in tracked_paths}
    inbound: dict[str, set[str]] = {}

    def add(target: str, source: str) -> None:
        if target == source:
            return
        inbound.setdefault(target, set()).add(source)

    for relative in inventory:
        if not relative.endswith(".md"):
            continue
        path = root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file():
            continue
        for target in outbound_targets(relative, path.read_text(encoding="utf-8")):
            add(target, relative)

    mkdocs = root / "mkdocs.yml"
    if mkdocs.is_file():
        for target in _mkdocs_nav_targets(mkdocs.read_text(encoding="utf-8")):
            add(target, "mkdocs.yml")
    return inbound


def check_docs_orphans(root: Path, tracked_paths: Iterable[str] | None = None) -> list[str]:
    """Report living pages that have no inbound Markdown or MkDocs nav link."""

    if tracked_paths is None:
        loaded = load_tracked_paths(root)
        if loaded is None:
            return ["docs orphans: git ls-files inventory unavailable"]
        inventory = loaded
    else:
        inventory = {path.replace("\\", "/") for path in tracked_paths}

    inbound = inbound_index(root, inventory)
    problems = [
        f"{relative}: {PROBLEM_SUFFIX}"
        for relative in inventory
        if is_living_page(relative) and not inbound.get(relative)
    ]
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracked = load_tracked_paths(root)
    if tracked is None:
        print("docs orphans: FAIL")
        print("git ls-files inventory unavailable")
        return 1

    problems = check_docs_orphans(root, tracked_paths=tracked)
    living = sum(1 for path in tracked if is_living_page(path))
    if living == 0:
        print("docs orphans: FAIL (0 living pages)")
        for problem in problems:
            print(problem)
        return 1
    if problems:
        for problem in problems:
            print(problem)
        return 1

    print(f"docs orphans: OK ({living} living pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
