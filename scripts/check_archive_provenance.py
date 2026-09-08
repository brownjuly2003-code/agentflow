"""Fail closed when archived documents omit required provenance facts.

Every tracked ``docs/archive/**/*.md`` page except ``README.md`` index pages must
state, within its first ``HEADER_WINDOW_LINES`` lines, the five facts required by
the archive contract in ``docs/archive/README.md``: original path, archive date
(ISO ``YYYY-MM-DD``), reason, current replacement, and content type. The
replacement fact is also satisfied implicitly when the ``Original path`` value
still names a tracked file: the undated original then *is* the living
replacement (for example an archived dated snapshot of a mutable perf record).
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

ARCHIVE_DIR = "docs/archive"
HEADER_WINDOW_LINES = 40
REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "original_path": frozenset({"Original path", "Original location"}),
    "archived_on": frozenset({"Archived", "Archived on"}),
    "reason": frozenset({"Reason"}),
    "replacement": frozenset(
        {
            "Current replacement",
            "Current design",
            "Current sources",
            "Replacement",
        }
    ),
    "content_type": frozenset({"Content type"}),
}
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

_LEADING_MARKERS = frozenset({">", "-", "*"})


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


def is_archived_document(path: str) -> bool:
    relative = path.replace("\\", "/")
    if not relative.endswith(".md"):
        return False
    posix = PurePosixPath(relative)
    if posix.name == "README.md":
        return False
    try:
        posix.relative_to(ARCHIVE_DIR)
    except ValueError:
        return False
    return True


def _normalize_header_line(raw: str) -> str:
    text = raw.strip()
    while text and text[0] in _LEADING_MARKERS:
        text = text[1:].lstrip()
    return text


def _header_window(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()[:HEADER_WINDOW_LINES]


def _line_has_label(normalized: str, label: str) -> bool:
    return normalized.startswith(f"{label}:")


def _label_value(normalized: str, labels: Iterable[str]) -> str | None:
    """Return the text after ``<label>:`` for the first matching label."""

    for label in labels:
        if _line_has_label(normalized, label):
            return normalized[len(label) + 1 :].strip()
    return None


def original_path_value(window: Iterable[str]) -> str | None:
    """Return the normalized ``Original path`` value from a header window, if any."""

    for line in window:
        value = _label_value(line, REQUIRED_FIELDS["original_path"])
        if value is None:
            continue
        link = re.fullmatch(r"\[[^\]]*\]\(([^)]+)\)", value)
        if link:
            value = link.group(1)
        return value.strip("*`_ ").replace("\\", "/")
    return None


def check_archive_provenance(root: Path, tracked_paths: Iterable[str] | None = None) -> list[str]:
    """Report missing provenance facts in tracked archived Markdown documents."""

    if tracked_paths is None:
        loaded = load_tracked_paths(root)
        if loaded is None:
            return ["archive provenance: git ls-files inventory unavailable"]
        inventory = loaded
    else:
        inventory = {path.replace("\\", "/") for path in tracked_paths}

    problems: list[str] = []
    for relative in inventory:
        if not is_archived_document(relative):
            continue
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file():
            continue
        window = [_normalize_header_line(line) for line in _header_window(target)]
        for field, labels in REQUIRED_FIELDS.items():
            matching = [
                line for line in window if any(_line_has_label(line, label) for label in labels)
            ]
            if not matching and field == "replacement":
                original = original_path_value(window)
                if original and original != relative and original in inventory:
                    continue
            if not matching:
                expected = ", ".join(sorted(labels))
                problems.append(f"{relative}: missing {field} (expected one of: {expected})")
                continue
            if field == "archived_on" and not any(ISO_DATE.search(line) for line in matching):
                problems.append(f"{relative}: archived_on has no ISO date")
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracked = load_tracked_paths(root)
    if tracked is None:
        print("archive provenance: FAIL")
        print("git ls-files inventory unavailable")
        return 1

    problems = check_archive_provenance(root, tracked_paths=tracked)
    archived = sum(1 for path in tracked if is_archived_document(path))
    if archived == 0:
        print("archive provenance: FAIL (0 archived documents)")
        for problem in problems:
            print(problem)
        return 1
    if problems:
        for problem in problems:
            print(problem)
        return 1

    print(f"archive provenance: OK ({archived} archived documents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
