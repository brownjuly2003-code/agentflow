#!/usr/bin/env python3
"""
Bump version, create git tag, trigger CI publish.

Usage:
  python scripts/release.py patch   # 1.0.0 -> 1.0.1
  python scripts/release.py minor   # 1.0.0 -> 1.1.0
  python scripts/release.py major   # 1.0.0 -> 2.0.0
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "sdk" / "pyproject.toml"
PACKAGE_JSON_PATH = ROOT / "sdk-ts" / "package.json"
INIT_PATH = ROOT / "sdk" / "agentflow" / "__init__.py"
CHANGELOG_PATH = ROOT / "sdk" / "CHANGELOG.md"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PYPROJECT_VERSION_RE = re.compile(r'(?m)^version = "([^"]+)"$')
INIT_VERSION_RE = re.compile(r'(?m)^__version__ = "([^"]+)"$')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an AgentFlow SDK release.")
    parser.add_argument("part", choices=("patch", "minor", "major"))
    return parser.parse_args()


def read_versions() -> tuple[str, str, str]:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    package_json = json.loads(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
    init_match = INIT_VERSION_RE.search(INIT_PATH.read_text(encoding="utf-8"))
    if init_match is None:
        raise SystemExit(f"Could not find __version__ in {INIT_PATH}")
    return (
        pyproject["project"]["version"],
        package_json["version"],
        init_match.group(1),
    )


def ensure_versions_match(versions: tuple[str, str, str]) -> str:
    python_version, ts_version, runtime_version = versions
    if python_version != ts_version or python_version != runtime_version:
        raise SystemExit(
            "Version mismatch detected. "
            f"pyproject={python_version}, package.json={ts_version}, __init__={runtime_version}"
        )
    if not VERSION_RE.fullmatch(python_version):
        raise SystemExit(f"Unsupported version format: {python_version}")
    return python_version


def bump_version(current_version: str, part: str) -> str:
    major, minor, patch = (int(value) for value in current_version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def replace_version(path: Path, pattern: re.Pattern[str], new_version: str) -> None:
    original = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(
        lambda match: match.group(0).replace(match.group(1), new_version, 1),
        original,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"Could not update version in {path}")
    path.write_text(updated, encoding="utf-8", newline="\n")


def replace_package_json_version(path: Path, new_version: str) -> None:
    package_json = json.loads(path.read_text(encoding="utf-8"))
    package_json["version"] = new_version
    path.write_text(json.dumps(package_json, indent=2) + "\n", encoding="utf-8", newline="\n")


def update_changelog(new_version: str) -> None:
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    heading = f"## [{new_version}] - {date.today().isoformat()}"
    if heading in changelog:
        raise SystemExit(f"Changelog entry already exists for {new_version}")

    marker = "## ["
    index = changelog.find(marker)
    if index == -1:
        raise SystemExit(f"Could not find insertion point in {CHANGELOG_PATH}")

    new_entry = (
        f"{heading}\n\n"
        "### Changed\n"
        f"- Release {new_version}.\n\n"
    )
    updated = changelog[:index] + new_entry + changelog[index:]
    CHANGELOG_PATH.write_text(updated, encoding="utf-8", newline="\n")


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def ensure_tag_absent(tag_name: str) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag_name}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise SystemExit(f"Tag already exists: {tag_name}")


def commit_and_tag(new_version: str) -> None:
    files_to_stage = [
        "sdk/pyproject.toml",
        "sdk-ts/package.json",
        "sdk/agentflow/__init__.py",
        "sdk/CHANGELOG.md",
    ]
    run_git("add", "--", *files_to_stage)
    run_git("commit", "-m", f"release: v{new_version}")
    run_git("tag", f"sdk-v{new_version}")


def main() -> int:
    args = parse_args()
    current_version = ensure_versions_match(read_versions())
    next_version = bump_version(current_version, args.part)
    ensure_tag_absent(f"sdk-v{next_version}")

    replace_version(PYPROJECT_PATH, PYPROJECT_VERSION_RE, next_version)
    replace_package_json_version(PACKAGE_JSON_PATH, next_version)
    replace_version(INIT_PATH, INIT_VERSION_RE, next_version)
    update_changelog(next_version)
    commit_and_tag(next_version)

    print(f"Released version {next_version}")
    print(f"Created commit: release: v{next_version}")
    print(f"Created tag: sdk-v{next_version}")
    print("Next steps:")
    print("  git push")
    print("  git push --tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
