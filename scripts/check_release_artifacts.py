"""Fail release artifacts that contain operational secrets or local state."""

from __future__ import annotations

import argparse
import fnmatch
import glob
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN_MEMBER_PATTERNS = (
    ".env",
    ".env.*",
    "*/.env",
    "*/.env.*",
    "config/api_keys.yaml",
    "config/tenants.yaml",
    "config/webhooks.yaml",
    "docker/**/secrets/**",
    "**/secrets/**",
    "*secret*",
    "**/*secret*",
)

ALLOWED_MEMBER_PATTERNS = (
    "agentflow/templates/*/.env.example.tmpl",
    "*/agentflow/templates/*/.env.example.tmpl",
)


def find_forbidden_members(artifact_path: Path) -> list[str]:
    violations: list[str] = []

    for member in _artifact_members(artifact_path):
        if _is_forbidden_member(member):
            violations.append(member)

    return violations


def _artifact_members(artifact_path: Path) -> list[str]:
    if zipfile.is_zipfile(artifact_path):
        with zipfile.ZipFile(artifact_path) as archive:
            return sorted(_normalize_member(name) for name in archive.namelist())

    if tarfile.is_tarfile(artifact_path):
        with tarfile.open(artifact_path) as archive:
            return sorted(_normalize_member(member.name) for member in archive.getmembers())

    raise ValueError(f"Unsupported artifact format: {artifact_path}")


def _normalize_member(member: str) -> str:
    return member.replace("\\", "/").lstrip("./")


def _is_forbidden_member(member: str) -> bool:
    candidates = [member]
    parts = member.split("/", 1)
    if len(parts) == 2:
        candidates.append(parts[1])

    if any(
        fnmatch.fnmatchcase(candidate, pattern)
        for candidate in candidates
        for pattern in ALLOWED_MEMBER_PATTERNS
    ):
        return False

    return any(
        fnmatch.fnmatchcase(candidate, pattern)
        for candidate in candidates
        for pattern in FORBIDDEN_MEMBER_PATTERNS
    )


def _expand_artifacts(values: list[str]) -> list[Path]:
    artifacts: list[Path] = []

    for value in values:
        matches = glob.glob(value)
        if matches:
            artifacts.extend(Path(match) for match in matches)
        else:
            artifacts.append(Path(value))

    return artifacts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail release artifacts that contain forbidden file paths.",
    )
    parser.add_argument("artifacts", nargs="+", help="Artifact paths or glob patterns.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failed = False

    for artifact in _expand_artifacts(args.artifacts):
        violations = find_forbidden_members(artifact)
        if not violations:
            print(f"{artifact}: OK")
            continue

        failed = True
        print(f"{artifact}: forbidden members")
        for violation in violations:
            print(f"  {violation}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
