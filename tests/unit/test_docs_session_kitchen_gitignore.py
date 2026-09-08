"""Kitchen session artifacts must be named in .gitignore, not left untracked.

``.myflow/`` is MyFlow controller state (tasks, journals, writer prompts,
review packs). Root ``SESSION_LOG*.md`` files are per-session chronology,
overwritten wholesale. Neither is product documentation. Untracked-but-
unignored is one ``git add -A`` away from a public repo, and a tracked
root ``SESSION_LOG*.md`` is rejected by the repository-root Markdown
allowlist. Naming both in the internal-working-notes block makes that
impossible rather than merely unlikely.

AGENTS.md and docs/operations/cycle-guard.md were landed as tracked
product/operations docs and must stay admitted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_docs_root_placement import (
    REPO_ROOT_MARKDOWN_ALLOWLIST,
    check_repo_root_markdown_placement,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GITIGNORE = PROJECT_ROOT / ".gitignore"
KITCHEN_HEADING = "# Internal working notes / autonomous-session artifacts"
KITCHEN_END = "# Audit F-11:"
MYFLOW_PATTERN = "/.myflow/"
SESSION_LOG_PATTERN = "/SESSION_LOG*.md"
TRACKED_PRODUCT_DOCS = (
    "AGENTS.md",
    "docs/operations/cycle-guard.md",
)
# Directory probes use a trailing slash so MUSTBEDIR patterns match without
# the directory existing on disk (fresh clone / CI).
EXISTING_KITCHEN_PATHS = (
    ".claude/",
    "AGENT_STATE.md",
)
SESSION_LOG_PATHS = (
    "SESSION_LOG.md",
    "SESSION_LOG_2026-09-05.md",
    "SESSION_LOG_2099-12-31.md",
)


def _kitchen_block_lines() -> list[str]:
    text = GITIGNORE.read_text(encoding="utf-8")
    start = text.index(KITCHEN_HEADING)
    end = text.index(KITCHEN_END, start)
    return text[start:end].splitlines()


def _check_ignore(path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", "--", path],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _matching_rule(path: str) -> str:
    result = _check_ignore(path)
    assert result.returncode == 0, (
        f"{path} must be ignored; git check-ignore -v: {result.stdout!r} {result.stderr!r}"
    )
    # git check-ignore -v: <source>:<linenum>:<pattern><TAB><pathname>
    rule = result.stdout.splitlines()[0].split("\t", 1)[0]
    source, _line, pattern = rule.split(":", 2)
    assert source.replace("\\", "/").endswith(".gitignore"), result.stdout
    return pattern


def test_control_existing_repo_root_markdown_allowlist_still_accepts_agents_md() -> None:
    tracked = set(REPO_ROOT_MARKDOWN_ALLOWLIST)

    assert "AGENTS.md" in tracked
    assert "SESSION_LOG.md" not in tracked
    assert "SESSION_LOG_2026-09-05.md" not in tracked
    assert check_repo_root_markdown_placement(tracked) == []


def test_control_tracked_product_docs_remain_admitted() -> None:
    for path in TRACKED_PRODUCT_DOCS:
        ignore = _check_ignore(path)
        assert ignore.returncode == 1, (
            f"{path} must not be ignored; git check-ignore -v: {ignore.stdout!r}"
        )
        listed = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert listed.returncode == 0, f"{path} must stay tracked"


def test_control_existing_kitchen_patterns_still_match() -> None:
    lines = _kitchen_block_lines()
    for path in EXISTING_KITCHEN_PATHS:
        pattern = f"/{path}"
        assert pattern in lines
        assert _matching_rule(path) == pattern


def test_session_log_stays_off_the_repo_root_markdown_allowlist() -> None:
    tracked = set(REPO_ROOT_MARKDOWN_ALLOWLIST) | {
        "SESSION_LOG.md",
        "SESSION_LOG_2026-09-05.md",
    }
    problems = check_repo_root_markdown_placement(tracked)

    assert "unexpected tracked repository-root Markdown: SESSION_LOG.md" in problems
    assert "unexpected tracked repository-root Markdown: SESSION_LOG_2026-09-05.md" in problems
    assert "unexpected tracked repository-root Markdown: AGENTS.md" not in problems


def test_kitchen_block_names_myflow_and_root_session_logs() -> None:
    lines = _kitchen_block_lines()

    assert MYFLOW_PATTERN in lines
    assert SESSION_LOG_PATTERN in lines
    assert "/AGENTS.md" not in lines
    assert not any("cycle-guard" in line for line in lines)


def test_myflow_controller_state_is_ignored() -> None:
    assert _matching_rule(".myflow/") == MYFLOW_PATTERN
    assert _matching_rule(".myflow/tasks.json") == MYFLOW_PATTERN


def test_root_session_logs_are_ignored() -> None:
    for path in SESSION_LOG_PATHS:
        assert _matching_rule(path) == SESSION_LOG_PATTERN, path


def test_session_log_pattern_is_root_anchored() -> None:
    result = _check_ignore("docs/SESSION_LOG.md")
    assert result.returncode == 1, result.stdout


def test_git_status_does_not_list_kitchen_session_paths() -> None:
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--",
            ".myflow",
            "SESSION_LOG.md",
            "SESSION_LOG_2026-09-05.md",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    listed = {
        line[3:].replace("\\", "/").rstrip("/")
        for line in result.stdout.splitlines()
        if line.strip()
    }
    assert ".myflow" not in listed
    assert "SESSION_LOG.md" not in listed
    assert "SESSION_LOG_2026-09-05.md" not in listed
