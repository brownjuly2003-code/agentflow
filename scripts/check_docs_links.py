"""Fail closed when living docs point at missing local files or source paths."""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Directories holding immutable run evidence: a dated record states what was
# true at its own commit and must not be rewritten when code moves.
# docs/evidence/INDEX.md is the living catalogue and remains checked below.
HISTORICAL_DIRECTORIES = (
    "docs/perf",
    "docs/evidence",
    "docs/migration",
    "docs/codex-tasks",
)

# Named immutable documents outside those directories.
# - docs/SESSION_HANDOFF.md: gitignored (.gitignore:174), reachable via rglob
#   on a workstation that still has it.
HISTORICAL_FILES = ("docs/SESSION_HANDOFF.md",)

# Paths a living doc may legitimately name although they are never committed:
# - environment tfvars are generated from *.tfvars.example (docs/operations/aws-oidc-setup.md)
# - dist/ and sdk/dist/ are local build output an operator is told to clear
KNOWN_ABSENT_BY_DESIGN = (
    "infrastructure/terraform/environments/staging.tfvars",
    "infrastructure/terraform/environments/prod.tfvars",
    "dist",
    "sdk/dist",
)

# Artefacts deliberately not committed, so CI cannot validate them. Keep this
# list prefix/glob-explicit — never exclude a whole live directory.
KNOWN_UNTRACKED_REFERENCES = (
    ".codex-grok-tasks/",  # prefix; .gitignore:192
    "AGENT_STATE.md",  # .gitignore:137
    "_NEXT_SESSION.md",  # .gitignore:99
    "docs/SESSION_HANDOFF.md",  # .gitignore:174
    "second-opinion-*.md",  # root files only; .gitignore:158
)

REPO_PATH_PREFIXES = (
    "src/",
    "sdk/",
    "sdk-ts/",
    "scripts/",
    "helm/",
    "tests/",
    "config/",
    "docs/",
    "k8s/",
    "infrastructure/",
    "integrations/",
    "packaging/",
    "warehouse/",
    "monitoring/",
    ".github/",
)

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
BACKTICK_RE = re.compile(r"`([^`]+)`")
# Glob/template characters (*{}<>|…) are excluded so the match stops before a
# wildcard; truncated prefixes such as config/contracts/metric. are then
# rejected by _looks_like_repo_path.
EMBEDDED_REPO_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])("
    r"(?:src|sdk|sdk-ts|scripts|helm|tests|config|docs|k8s|"
    r"infrastructure|integrations|packaging|warehouse|monitoring|\.github)"
    r"/[A-Za-z0-9_./-]+)"
)
LOCAL_ARTIFACT_RE = re.compile(r"\.local\.(ya?ml|json|env)$", re.IGNORECASE)
LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")
REJECT_CHARS = "*{}<>|…"
_TRACKED_PATHS_CACHE: dict[Path, set[str] | None] = {}


def is_historical_evidence(relative: str) -> bool:
    """Return True when *relative* is immutable historical evidence."""

    posix = relative.replace("\\", "/")
    if posix == "docs/evidence/INDEX.md":
        return False
    if posix in HISTORICAL_FILES:
        return True
    return any(
        posix == directory or posix.startswith(f"{directory}/")
        for directory in HISTORICAL_DIRECTORIES
    )


def iter_living_docs(root: Path, tracked_paths: set[str] | None = None) -> list[Path]:
    """Return markdown files this checker is responsible for under *root*.

    Enumeration follows the git tracked set when it is available, so the set of
    documents checked is the same here and on a clean CI checkout. Without git
    it falls back to walking the filesystem.

    Deliberate scope: README.md, SECURITY.md, and living docs/**/*.md are
    checked after subtracting immutable evidence directories and named files.
    """

    tracked = load_tracked_paths(root) if tracked_paths is None else tracked_paths
    candidates: list[Path] = []
    if tracked is not None:
        candidates = [
            root / relative
            for relative in sorted(tracked)
            if relative.endswith(".md")
            and (relative in ("README.md", "SECURITY.md") or relative.startswith("docs/"))
        ]
    else:
        candidates = [root / "README.md", root / "SECURITY.md"]
        docs_root = root / "docs"
        if docs_root.is_dir():
            candidates.extend(sorted(docs_root.rglob("*.md")))
    living: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if is_historical_evidence(relative):
            continue
        living.append(path)
    return living


def load_tracked_paths(root: Path) -> set[str] | None:
    """Return POSIX-relative tracked paths for *root*, or None if git cannot run.

    Cached per resolved root. A ``None`` result means callers must fall back
    to the filesystem and announce that fallback in the report header.
    """

    resolved = root.resolve()
    if resolved in _TRACKED_PATHS_CACHE:
        cached = _TRACKED_PATHS_CACHE[resolved]
        return None if cached is None else set(cached)
    tracked = _read_git_tracked_paths(resolved)
    _TRACKED_PATHS_CACHE[resolved] = tracked
    return None if tracked is None else set(tracked)


def _read_git_tracked_paths(root: Path) -> set[str] | None:
    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if probe.returncode != 0:
        return None
    toplevel = Path(probe.stdout.strip())
    try:
        if toplevel.resolve() != root.resolve():
            return None
    except OSError:
        return None
    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listed.returncode != 0:
        return None
    return {part.decode("utf-8").replace("\\", "/") for part in listed.stdout.split(b"\0") if part}


def _posix_path(relative: str) -> str:
    posix = relative.strip().replace("\\", "/")
    while posix.startswith("./"):
        posix = posix[2:]
    return posix


def _is_known_untracked(relative: str) -> bool:
    posix = _posix_path(relative)
    for pattern in KNOWN_UNTRACKED_REFERENCES:
        if pattern.endswith("/"):
            prefix = pattern.rstrip("/")
            if posix == prefix or posix.startswith(f"{prefix}/"):
                return True
        elif "*" in pattern:
            if "/" not in posix and fnmatch.fnmatch(posix, pattern):
                return True
        elif posix == pattern:
            return True
    return False


def _has_repo_prefix(candidate: str) -> bool:
    for prefix in REPO_PATH_PREFIXES:
        base = prefix.rstrip("/")
        if candidate == base or candidate.startswith(f"{base}/"):
            return True
    return False


def _looks_like_repo_path(text: str) -> bool:
    candidate = text.strip().replace("\\", "/")
    if candidate.endswith("/"):
        candidate = candidate.rstrip("/")
    if not candidate or " " in candidate:
        return False
    # Markdown wrap truncation leaves a dangling hyphen or underscore.
    if candidate.endswith(("-", "_")):
        return False
    # Glob match stopped before * and left a trailing dot (metric.).
    if candidate.endswith("."):
        return False
    if any(char in candidate for char in REJECT_CHARS):
        return False
    if LOCAL_ARTIFACT_RE.search(candidate):
        return False
    return _has_repo_prefix(candidate)


def _normalize_repo_path(text: str) -> str | None:
    stripped = text.strip().replace("\\", "/")
    if "::" in stripped:
        stripped = stripped.split("::", 1)[0]
    stripped = LINE_SUFFIX_RE.sub("", stripped).strip()
    if not _looks_like_repo_path(stripped):
        return None
    return stripped.rstrip("/")


def _repo_paths_in_backticks(inner: str) -> list[str]:
    normalized = _normalize_repo_path(inner)
    if normalized is not None:
        return [normalized]
    found: list[str] = []
    for match in EMBEDDED_REPO_PATH_RE.finditer(inner):
        candidate = _normalize_repo_path(match.group(1))
        if candidate is not None:
            found.append(candidate)
    return found


def _path_claimed(root: Path, relative: str, tracked: set[str] | None) -> bool:
    posix = _posix_path(relative).rstrip("/")
    if not posix:
        return False
    if tracked is None:
        return (root / posix).exists()
    if posix in tracked:
        return True
    prefix = f"{posix}/"
    return any(path.startswith(prefix) for path in tracked)


def check_docs_links(
    root: Path,
    tracked_paths: set[str] | None = None,
) -> list[str]:
    """Return living-doc problems as ``file:line: ...`` strings.

    Pass *tracked_paths* to inject the git tracked set (tests). When omitted,
    the checker loads ``git ls-files -z`` once per root; if git is unavailable
    it falls back to ``Path.exists()``.
    """

    root = root.resolve()
    tracked = load_tracked_paths(root) if tracked_paths is None else tracked_paths
    problems: list[str] = []
    for document in iter_living_docs(root, tracked):
        relative = document.relative_to(root).as_posix()
        text = document.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            problems.extend(_link_problems(root, document, relative, line_number, line, tracked))
            problems.extend(_source_path_problems(root, relative, line_number, line, tracked))
    return problems


def _link_problems(
    root: Path,
    document: Path,
    relative: str,
    line_number: int,
    line: str,
    tracked: set[str] | None,
) -> Iterable[str]:
    for target in MARKDOWN_LINK_RE.findall(line):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        resolved = (document.parent / path_part).resolve()
        try:
            claimed = resolved.relative_to(root).as_posix()
        except ValueError:
            yield f"{relative}:{line_number}: missing link target {target!r}"
            continue
        if _is_known_untracked(claimed):
            continue
        if not _path_claimed(root, claimed, tracked):
            yield f"{relative}:{line_number}: missing link target {target!r}"


def _source_path_problems(
    root: Path,
    relative: str,
    line_number: int,
    line: str,
    tracked: set[str] | None,
) -> Iterable[str]:
    seen: set[str] = set()
    for inner in BACKTICK_RE.findall(line):
        if _is_known_untracked(inner.strip()):
            continue
        for repo_path in _repo_paths_in_backticks(inner):
            if repo_path in seen:
                continue
            seen.add(repo_path)
            if repo_path in KNOWN_ABSENT_BY_DESIGN:
                continue
            if _is_known_untracked(repo_path):
                continue
            if not _path_claimed(root, repo_path, tracked):
                yield f"{relative}:{line_number}: missing source path {repo_path!r}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    tracked = load_tracked_paths(root)
    if tracked is None:
        print("docs link check: filesystem fallback (git ls-files unavailable)")
    problems = check_docs_links(root, tracked_paths=tracked)
    if problems:
        print("docs link check: FAIL")
        for problem in problems:
            print(problem)
        return 1
    print("docs link check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
