"""Fail closed when docs contain replacement characters or broken heading anchors.

Two mechanical facts are checked:

* every tracked ``*.md`` file decodes as strict UTF-8 and contains no U+FFFD;
* every ``](target#fragment)`` link written from a living page resolves to a
  heading id that MkDocs would assign on a tracked Markdown target.

A living page is a tracked ``docs/**/*.md`` file that is not under
``HISTORICAL_DIRECTORIES``. Hubs (``docs/README.md``, ``docs/index.md``) *are*
living sources here. Historical pages may still be valid *targets*; they are
not scanned as sources. Non-Markdown targets (source lines, URLs) are ignored.

Heading ids come from the real MkDocs implementation:
``markdown.extensions.toc.slugify`` / ``unique`` (the ``markdown`` package
ships with ``mkdocs``, which is in the ``dev`` extra used by CI). Default
``toc.slugify`` drops non-ASCII, so a Cyrillic heading becomes ``""`` and then
``_1``, ``_2``, ... — this checker reproduces that and does not "improve" it.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath

from markdown.extensions.toc import slugify, unique

ROOT = Path(__file__).resolve().parents[1]

HISTORICAL_DIRECTORIES = (
    "docs/archive",
    "docs/decisions",
    "docs/dv2-multi-branch",
    "docs/evidence",
    "docs/migration",
    "docs/perf",
)
REPLACEMENT_CHARACTER = "\ufffd"
ANCHOR_LINK = re.compile(r"\]\(([^)\s#]*)#([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
ATTR_ID = re.compile(r"\{\s*#([^\s}]+)\s*\}\s*$")
OPEN_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
CODE_SPAN = re.compile(r"`([^`]+)`")
INLINE_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")

INVENTORY_PROBLEM = "docs anchors: git ls-files inventory unavailable"


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
    """Return whether *path* is a living docs page that may emit anchor links."""

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


def _iter_unfenced_lines(text: str) -> Iterator[str]:
    fence: tuple[str, int] | None = None
    close_pattern: re.Pattern[str] | None = None
    for line in text.splitlines():
        if fence is None:
            match = OPEN_FENCE.match(line)
            if match is not None:
                marker = match.group(2)
                info = match.group(3)
                if marker[0] == "`" and "`" in info:
                    yield line
                    continue
                fence = (marker[0], len(marker))
                close_pattern = re.compile(
                    rf"^( {{0,3}}){re.escape(marker[0])}{{{len(marker)},}}[ \t]*$"
                )
                continue
            yield line
            continue
        if close_pattern is not None and close_pattern.match(line):
            fence = None
            close_pattern = None


def _visible_heading_text(raw: str) -> str:
    text = CODE_SPAN.sub(r"\1", raw)
    text = INLINE_LINK.sub(r"\1", text)
    return text.replace("*", "").strip()


def heading_ids(text: str) -> set[str]:
    """Return the heading ids MkDocs would assign for *text*."""

    seen: set[str] = set()
    ids: set[str] = set()
    for line in _iter_unfenced_lines(text):
        match = HEADING.match(line)
        if match is None:
            continue
        raw = match.group(2)
        attr = ATTR_ID.search(raw)
        if attr is not None:
            ident = unique(attr.group(1), seen)
        else:
            ident = unique(slugify(_visible_heading_text(raw), "-"), seen)
        ids.add(ident)
    return ids


def anchor_links(source: str, text: str) -> list[tuple[int, str, str]]:
    """Return ``(line, repo-relative target, fragment)`` for Markdown anchors."""

    source_posix = source.replace("\\", "/")
    found: list[tuple[int, str, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in ANCHOR_LINK.finditer(line):
            raw_target, fragment = match.group(1), match.group(2)
            if "://" in raw_target or raw_target.lower().startswith("mailto:"):
                continue
            if not raw_target:
                found.append((line_number, source_posix, fragment))
                continue
            path_only = raw_target.split("?", 1)[0].rstrip("/")
            if not path_only.endswith(".md"):
                continue
            parent = PurePosixPath(source_posix).parent
            combined = path_only if str(parent) == "." else f"{parent}/{path_only}"
            found.append((line_number, _normalize_posix(combined), fragment))
    return found


def check_replacement_characters(root: Path, tracked_paths: Iterable[str]) -> list[str]:
    """Report tracked Markdown files that are not strict UTF-8 or contain U+FFFD."""

    problems: list[str] = []
    for relative in sorted({path.replace("\\", "/") for path in tracked_paths}):
        if not relative.endswith(".md"):
            continue
        path = root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file():
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{relative}: not valid UTF-8")
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if REPLACEMENT_CHARACTER in line:
                problems.append(f"{relative}:{line_number}: replacement character U+FFFD")
                break
    return problems


def _heading_ids_for(root: Path, relative: str, cache: dict[str, set[str]]) -> set[str]:
    if relative not in cache:
        path = root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file():
            cache[relative] = set()
        else:
            try:
                cache[relative] = heading_ids(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                cache[relative] = set()
    return cache[relative]


def _living_anchor_links(root: Path, inventory: set[str]) -> list[tuple[str, int, str, str]]:
    found: list[tuple[str, int, str, str]] = []
    for relative in inventory:
        if not is_living_page(relative):
            continue
        path = root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, target, fragment in anchor_links(relative, text):
            found.append((relative, line_number, target, fragment))
    return found


def check_docs_anchors(root: Path, tracked_paths: Iterable[str] | None = None) -> list[str]:
    """Report replacement-character and broken-anchor problems, sorted."""

    if tracked_paths is None:
        loaded = load_tracked_paths(root)
        if loaded is None:
            return [INVENTORY_PROBLEM]
        inventory = loaded
    else:
        inventory = {path.replace("\\", "/") for path in tracked_paths}

    problems = check_replacement_characters(root, inventory)
    heading_cache: dict[str, set[str]] = {}
    for relative, line_number, target, fragment in _living_anchor_links(root, inventory):
        if target not in inventory or not target.endswith(".md"):
            problems.append(
                f"{relative}:{line_number}: broken anchor '{target}#{fragment}' (no such page)"
            )
            continue
        if fragment not in _heading_ids_for(root, target, heading_cache):
            problems.append(
                f"{relative}:{line_number}: broken anchor '{target}#{fragment}' (no such heading)"
            )
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracked = load_tracked_paths(root)
    if tracked is None:
        print("docs anchors: FAIL")
        print(INVENTORY_PROBLEM)
        return 1

    problems = check_docs_anchors(root, tracked_paths=tracked)
    markdown_files = sum(1 for path in tracked if path.endswith(".md"))
    link_count = len(_living_anchor_links(root, tracked))
    if problems:
        for problem in problems:
            print(problem)
        return 1
    if link_count == 0:
        print("docs anchors: FAIL (0 anchor links)")
        return 1

    print(f"docs anchors: OK ({link_count} anchor links, {markdown_files} Markdown files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
