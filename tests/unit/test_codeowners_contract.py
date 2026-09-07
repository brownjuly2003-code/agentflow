from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CODEOWNERS_PATH = PROJECT_ROOT / ".github" / "CODEOWNERS"
REPOSITORY_OWNER = "@brownjuly2003-code"
PROTECTED_SURFACES = (
    ".github/workflows/**",
    "infrastructure/**",
    "helm/**",
    "src/agentflow_runtime/serving/api/auth/**",
    "src/agentflow_runtime/serving/api/middleware/**",
    "scripts/release.py",
    "scripts/evaluate_trivy_policy.py",
    "scripts/run_pip_audit_scan.py",
    "security/trivy-waivers.json",
    "config/project_claims.toml",
    "SECURITY.md",
    "docs/release-*.md",
)


@dataclass(frozen=True)
class CodeownersRule:
    pattern: str
    owners: tuple[str, ...]
    line_number: int


def _read_rules() -> list[CodeownersRule]:
    assert CODEOWNERS_PATH.is_file(), ".github/CODEOWNERS is required"

    rules: list[CodeownersRule] = []
    for line_number, raw_line in enumerate(
        CODEOWNERS_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        fields = line.split()
        assert len(fields) >= 2, f"CODEOWNERS line {line_number} has no owner: {raw_line!r}"
        pattern, *owners = fields
        assert all(owner.startswith("@") for owner in owners), (
            f"CODEOWNERS line {line_number} has an invalid owner: {raw_line!r}"
        )
        rules.append(CodeownersRule(pattern, tuple(owners), line_number))

    assert rules, ".github/CODEOWNERS has no ownership rules"
    return rules


def _git_pathspec(pattern: str) -> str:
    pathspec = pattern.removeprefix("/")
    if pathspec.endswith("/"):
        pathspec += "**"
    return pathspec


def _tracked_paths(pathspec: str) -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--", pathspec],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()}


def test_codeowners_file_parses_with_nonempty_owners() -> None:
    _read_rules()


def test_every_codeowners_pattern_matches_a_tracked_path() -> None:
    for rule in _read_rules():
        matches = _tracked_paths(_git_pathspec(rule.pattern))
        assert matches, (
            f"CODEOWNERS line {rule.line_number} pattern matches no tracked path: {rule.pattern}"
        )


def test_protected_surfaces_are_owned_by_repository_owner() -> None:
    owners_by_path: dict[str, tuple[str, ...]] = {}
    for rule in _read_rules():
        for path in _tracked_paths(_git_pathspec(rule.pattern)):
            owners_by_path[path] = rule.owners

    for surface in PROTECTED_SURFACES:
        protected_paths = _tracked_paths(surface)
        assert protected_paths, f"protected surface matches no tracked path: {surface}"
        incorrectly_owned = sorted(
            path for path in protected_paths if REPOSITORY_OWNER not in owners_by_path.get(path, ())
        )
        assert not incorrectly_owned, (
            f"{surface} is not owned by {REPOSITORY_OWNER}: {incorrectly_owned}"
        )
